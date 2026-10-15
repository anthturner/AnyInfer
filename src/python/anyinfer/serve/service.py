"""Service definitions that keep the sidecar running across logins and reboots.

The "no Python required" delivery path is finished right up to the last step: a standalone
sidecar exists, and then somebody has to keep a terminal window open. What is missing is a
systemd unit, a launchd agent, or a scheduled task — five decisions (working directory,
config path, restart policy, token handling, whether to bind loopback) that every operator
otherwise re-derives, and the security-relevant ones are the easiest to get wrong.

Rendering is **pure**: `render_service` builds text and paths and touches nothing, so all
three platforms' definitions are testable from any one of them. `write_service` is the
side-effecting half, and it is deliberately a separate call — printing before writing is
the whole posture of this module, and that only works if generation is free.

Nothing here supervises anything. The platform's own manager starts, stops, and restarts
the service; this produces the file that manager reads, and the commands a human runs.

Two rules are enforced at *generation* time rather than left to the running server:

- a definition that binds beyond loopback requires both an explicit exposure flag and a
  token, so a unit that would survive reboots as an unauthenticated LLM gateway cannot be
  produced at all;
- the bearer token never appears in the definition body. It goes to a private environment
  file, or on Windows, where a file mode means little — it is not written at all and the
  operator is told to set the variable instead.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Literal

from ..errors import ConfigError

__all__ = [
    "LAUNCHD_LABEL",
    "SERVICE_NAME",
    "TASK_NAME",
    "TOKEN_ENV_VAR",
    "ServiceDefinition",
    "ServicePlatform",
    "ServiceRequest",
    "ServiceScope",
    "current_platform",
    "render_service",
    "resolve_executable",
    "write_service",
]

SERVICE_NAME = "anyinfer-serve"
"""systemd unit name, without the ``.service`` suffix."""

LAUNCHD_LABEL = "dev.anyinfer.serve"
"""Reverse-DNS label launchd identifies the agent by."""

TASK_NAME = "AnyInfer Sidecar"
"""Scheduled-task name, as it appears in Task Scheduler."""

TOKEN_ENV_VAR = "ANYINFER_SERVE_TOKEN"
"""Variable the server reads its bearer token from, so it never enters a process listing."""

ServicePlatform = Literal["linux", "macos", "windows"]
"""Which service manager a definition is written for."""

ServiceScope = Literal["user", "system"]
"""Whose service it is.

``user`` needs no privileges anywhere: ``systemctl --user``, a LaunchAgent, and a per-user
scheduled task all install without elevation, which is why it is the default. ``system``
is generated and *printed*; running it is the operator's step, because a library CLI that
shells into ``sudo`` is not something to ship.
"""

_LOOPBACK = "127.0.0.1"


def current_platform() -> ServicePlatform:
    """Which service manager this machine uses."""
    # `sys.platform` narrows to a literal for the interpreter mypy is checking, so the
    # other two branches read as unreachable to it; the value is genuinely a runtime fact.
    mapping: dict[str, ServicePlatform] = {"win32": "windows", "darwin": "macos"}
    return mapping.get(sys.platform, "linux")


@dataclass(frozen=True, slots=True)
class ServiceRequest:
    """What the generated service should run, and where it should live.

    Attributes:
        executable: Absolute path of the program the manager will launch.
        arguments: Arguments before the server's own flags. Empty for the standalone
            sidecar bundle, whose entry point already means "serve"; ``("serve",)`` for
            the ``anyinfer`` console script.
        config: Configuration file to pass, or ``None`` for none.
        host: Bind address.
        port: Bind port.
        expose: Concrete targets to advertise from ``/v1/models``.
        allow_remote_exposure: Whether a non-loopback bind was explicitly asked for.
        token: Bearer token clients must present. Written to a private environment file,
            never into the definition body.
        log_file: Where to send the server's output, or ``None``. Only Windows needs one —
            systemd and launchd already have a log sink, and nothing rotates it.
        working_directory: Directory the service runs in; defaults to the config's parent,
            or the executable's.
        scope: ``user`` or ``system``; see `ServiceScope`.
        platform: Which manager to write for; defaults to this machine's.
        root: Base directory the definition's paths are built under. The test seam: every
            install path is exercised against a temp root rather than a developer's real
            systemd, launchd, or Task Scheduler.
    """

    executable: PurePath
    arguments: tuple[str, ...] = ()
    config: PurePath | None = None
    host: str = _LOOPBACK
    port: int = 8080
    expose: tuple[str, ...] = ()
    allow_remote_exposure: bool = False
    token: str | None = None
    log_file: PurePath | None = None
    working_directory: PurePath | None = None
    scope: ServiceScope = "user"
    platform: ServicePlatform = field(default_factory=current_platform)
    root: PurePath | None = None

    @property
    def server_arguments(self) -> tuple[str, ...]:
        """The full argument vector, token excluded — it arrives by environment."""
        args = [*self.arguments, "--host", self.host, "--port", str(self.port)]
        if self.config is not None:
            args += ["--config", str(self.config)]
        if self.allow_remote_exposure:
            args.append("--allow-remote-exposure")
        for target in self.expose:
            args += ["--expose", target]
        return tuple(args)


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """One rendered service definition, and the commands that manage it.

    Attributes:
        platform: Which manager this is for.
        scope: Whose service it is.
        path: Where the definition file belongs.
        content: The file's text.
        encoding: How to write it. Windows' ``schtasks /XML`` reads UTF-16.
        install_commands: Commands that register and start it, in order. A list rather
            than one command because no manager does it in a single step — systemd needs a
            daemon reload before an enable, and pretending otherwise would print something
            that does not work.
        uninstall_commands: Commands that stop and deregister it, in order.
        status_commands: Read-only commands reporting what the manager thinks. Never a
            control verb: the moment this issues one it has become the process supervisor
            this module refuses to be.
        environment_path: Private file the bearer token belongs in, or ``None`` on a
            platform that cannot protect one. Set whether or not a token was configured,
            so ``uninstall`` can remove a file an earlier ``install`` wrote.
        environment_content: That file's text, empty when there is no token. Only a
            non-empty value is ever written.
        notes: Things the operator has to know that the file cannot say for itself.
    """

    platform: ServicePlatform
    scope: ServiceScope
    path: PurePath
    content: str
    encoding: str = "utf-8"
    install_commands: tuple[tuple[str, ...], ...] = ()
    uninstall_commands: tuple[tuple[str, ...], ...] = ()
    status_commands: tuple[tuple[str, ...], ...] = ()
    environment_path: PurePath | None = None
    environment_content: str = ""
    notes: tuple[str, ...] = ()

    @property
    def needs_elevation(self) -> bool:
        """Whether registering this definition requires administrative rights."""
        return self.scope == "system"


def resolve_executable() -> tuple[Path, tuple[str, ...]]:
    """Find a launcher for the sidecar that will still exist at the next boot.

    Returns:
        The absolute executable and the arguments that precede the server's own flags.

    Raises:
        ConfigError: If the only launcher available lives in a temporary or extraction
            directory. A unit pointing into a scratch directory is a unit that breaks on
            the next boot, and a broken unit is worse than no unit.
    """
    if getattr(sys, "frozen", False):
        # The standalone bundle's entry point already means "serve", so it takes the
        # server's flags directly.
        return Path(_checked(Path(sys.executable).resolve())), ()

    script = shutil.which("anyinfer")
    if script:
        candidate = Path(script).resolve()
        if not _is_transient(candidate):
            return candidate, ("serve",)

    # No console script on PATH, or one in a scratch directory: name the interpreter
    # instead. It is absolute, it is the one this process is running under, and a unit
    # built from it does not depend on PATH at all.
    return (
        Path(_checked(Path(sys.executable).resolve())),
        ("-m", "anyinfer.cli", "serve"),
    )


def render_service(request: ServiceRequest) -> ServiceDefinition:
    """Render the service definition for one request.

    Args:
        request: What to run and where the definition should live.

    Returns:
        The definition, with the commands that install, remove, and query it.

    Raises:
        ConfigError: If the executable is not absolute or lives somewhere transient, or if
            the request would produce a rebooting, unauthenticated, non-loopback gateway.
    """
    executable = request.executable
    if not _absolute_anywhere(executable):
        raise ConfigError(
            f"the service executable {executable} is not an absolute path",
            hint="a service definition cannot depend on the PATH of whoever installed it",
        )
    _checked(executable)
    _check_exposure(request)

    if request.platform == "linux":
        return _systemd(request, executable)
    if request.platform == "macos":
        return _launchd(request, executable)
    return _scheduled_task(request, executable)


def write_service(definition: ServiceDefinition, *, force: bool = False) -> tuple[Path, ...]:
    """Write a rendered definition and, if it has one, its private environment file.

    Args:
        definition: What to write.
        force: Replace files that already exist.

    Returns:
        The paths written, in the order they were written.

    Raises:
        ConfigError: If a file exists and ``force`` is false, or cannot be written.
    """
    written: list[Path] = []
    targets: list[tuple[Path, str, bool]] = [(Path(definition.path), definition.content, False)]
    if definition.environment_path is not None and definition.environment_content:
        targets.append((Path(definition.environment_path), definition.environment_content, True))

    for path, _content, _private in targets:
        if path.exists() and not force:
            raise ConfigError(
                f"{path} already exists",
                hint="pass --force to replace it, or --print to see it without writing",
            )
    for path, content, private in targets:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if private:
                # Created empty at 0600 before anything is written to it: writing first
                # and tightening afterwards leaves a window in which the token is
                # world-readable, which is the whole thing this mode exists to prevent.
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(content)
                path.chmod(0o600)
            else:
                path.write_text(content, encoding=definition.encoding)
        except OSError as exc:
            raise ConfigError(
                f"cannot write {path}: {exc}",
                hint="check the directory exists and is writable",
            ) from exc
        written.append(path)
    return tuple(written)


# ---- guards ----------------------------------------------------------------------------


def _check_exposure(request: ServiceRequest) -> None:
    """Refuse to generate a rebooting gateway that anyone on the network can call."""
    if request.host == _LOOPBACK or request.host == "localhost":
        return
    if not request.allow_remote_exposure:
        raise ConfigError(
            f"refusing to generate a service bound to {request.host}",
            hint=(
                "pass --allow-remote-exposure, and understand that this exposes every "
                "configured provider"
            ),
        )
    if not request.token:
        raise ConfigError(
            f"a service bound to {request.host} must require a bearer token",
            hint=(
                f"pass --token, or set {TOKEN_ENV_VAR} — an unauthenticated gateway that "
                "survives reboots is a credential laundering service"
            ),
        )


def _absolute_anywhere(path: PurePath) -> bool:
    """Whether a path is absolute under either convention.

    ``Path.is_absolute()`` answers for the interpreter's own platform, which would make a
    Linux unit un-renderable from a Windows machine, and rendering is meant to be pure
    and platform-independent precisely so all three definitions can be tested from any
    one of them.
    """
    text = str(path)
    return PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute()


def _flavoured(request: ServiceRequest, text: str) -> PurePath:
    """A pure path in the target platform's flavour, whatever this machine's is."""
    if request.platform == "windows":
        return PureWindowsPath(text)
    return PurePosixPath(text)


def _is_transient(path: PurePath) -> bool:
    """Whether a path lies in a temporary or PyInstaller extraction directory."""
    candidates = [Path(tempfile.gettempdir())]
    extraction = getattr(sys, "_MEIPASS", None)
    if extraction:
        candidates.append(Path(str(extraction)))
    for base in candidates:
        try:
            Path(path).resolve().relative_to(base.resolve())
        except (ValueError, OSError):
            continue
        return True
    return False


def _checked(path: PurePath) -> PurePath:
    """Return ``path``, refusing one that will not survive a reboot.

    Raises:
        ConfigError: If the path lies in a temporary or extraction directory.
    """
    if _is_transient(path):
        raise ConfigError(
            f"{path} is inside a temporary directory, so a service pointing at it would "
            "break on the next boot",
            hint=(
                "install AnyInfer into a stable location, or unpack the standalone "
                "sidecar somewhere permanent, then rerun this command"
            ),
        )
    return path


# ---- platform renderers ------------------------------------------------------------------


def _home(request: ServiceRequest) -> PurePath:
    """The base directory a user-scope definition hangs off."""
    if request.root is not None:
        return request.root
    return _flavoured(request, str(Path.home()))


def _system_root(request: ServiceRequest) -> PurePath:
    """The base directory a system-scope definition hangs off."""
    if request.root is not None:
        return request.root
    return _flavoured(request, "/")


def _working_directory(request: ServiceRequest, executable: PurePath) -> PurePath:
    """Where the service runs, so a relative path in its configuration still resolves."""
    if request.working_directory is not None:
        return request.working_directory
    if request.config is not None:
        return request.config.parent
    return executable.parent


def _quote(value: object) -> str:
    """Quote one argument for a shell-interpreted service line."""
    text = str(value)
    return "'" + text.replace("'", "'\\''") + "'"


def _systemd(request: ServiceRequest, executable: PurePath) -> ServiceDefinition:
    """A systemd unit, hardened by default.

    The hardening directives are on rather than offered: this process reads a
    configuration file and speaks HTTP, so it has no business writing to the filesystem,
    gaining privileges, or opening anything but IP sockets, and a default that has to be
    turned on is a default nobody has.
    """
    scope = request.scope
    systemctl: tuple[str, ...]
    if scope == "user":
        unit_path = _home(request) / ".config/systemd/user" / f"{SERVICE_NAME}.service"
        env_path = _home(request) / ".config/anyinfer" / "serve.env"
        systemctl = ("systemctl", "--user")
        wanted_by = "default.target"
    else:
        unit_path = _system_root(request) / "etc/systemd/system" / f"{SERVICE_NAME}.service"
        env_path = _system_root(request) / "etc/anyinfer" / "serve.env"
        systemctl = ("systemctl",)
        wanted_by = "multi-user.target"

    exec_start = " ".join([_shell_word(executable), *map(_shell_word, request.server_arguments)])
    lines = [
        "[Unit]",
        "Description=AnyInfer OpenAI-compatible sidecar",
        "Documentation=https://anyinfer.dev/serve/",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={exec_start}",
        f"WorkingDirectory={_working_directory(request, executable)}",
        # A leading dash: the unit still starts when there is no token to read, which is
        # the ordinary loopback case.
        f"EnvironmentFile=-{env_path}",
        "Restart=on-failure",
        "RestartSec=5",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "ProtectKernelTunables=true",
        "ProtectControlGroups=true",
        "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
    ]
    if request.log_file is not None:
        lines.append(f"StandardOutput=append:{request.log_file}")
        lines.append(f"StandardError=append:{request.log_file}")
        # ProtectSystem=strict makes everything read-only; the log directory is the one
        # place this service is allowed to write, and it has to be named to be writable.
        lines.append(f"ReadWritePaths={request.log_file.parent}")
    lines += ["", "[Install]", f"WantedBy={wanted_by}", ""]

    unit = f"{SERVICE_NAME}.service"
    return ServiceDefinition(
        platform="linux",
        scope=scope,
        path=unit_path,
        content="\n".join(lines),
        install_commands=(
            (*systemctl, "daemon-reload"),
            (*systemctl, "enable", "--now", unit),
        ),
        uninstall_commands=(
            (*systemctl, "disable", "--now", unit),
            (*systemctl, "daemon-reload"),
        ),
        status_commands=((*systemctl, "status", unit, "--no-pager"),),
        environment_path=env_path,
        environment_content=f"{TOKEN_ENV_VAR}={request.token}\n" if request.token else "",
        notes=_notes(
            request, "journalctl --user -u " + unit if scope == "user" else "journalctl -u " + unit
        ),
    )


def _shell_word(value: object) -> str:
    """Quote a word for a systemd ``ExecStart`` line, which is shell-like but not a shell."""
    text = str(value)
    if not text or any(character.isspace() for character in text) or '"' in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _launchd(request: ServiceRequest, executable: PurePath) -> ServiceDefinition:
    """A launchd agent, throttled so a crash loop does not spin.

    When a token is configured the agent runs through ``/bin/sh`` to source the private
    environment file. launchd has no ``EnvironmentFile`` and its ``EnvironmentVariables``
    dictionary lives in the plist itself, where the token must never go — a one-line shell
    wrapper is the smaller of the two compromises, and it supervises nothing.
    """
    scope = request.scope
    base = _home(request) if scope == "user" else _system_root(request)
    folder = "Library/LaunchAgents" if scope == "user" else "Library/LaunchDaemons"
    plist_path = base / folder / f"{LAUNCHD_LABEL}.plist"
    env_path = (
        _home(request) / ".config/anyinfer" / "serve.env"
        if scope == "user"
        else _system_root(request) / "etc/anyinfer" / "serve.env"
    )

    if request.token:
        script = f"set -a; . {_quote(env_path)}; set +a; exec {_quote(executable)} " + " ".join(
            _quote(argument) for argument in request.server_arguments
        )
        program: list[str] = ["/bin/sh", "-c", script]
    else:
        program = [str(executable), *request.server_arguments]

    entries = [
        ("Label", f"<string>{LAUNCHD_LABEL}</string>"),
        (
            "ProgramArguments",
            "<array>\n"
            + "\n".join(f"      <string>{_xml(part)}</string>" for part in program)
            + "\n    </array>",
        ),
        ("RunAtLoad", "<true/>"),
        ("KeepAlive", "<dict>\n      <key>SuccessfulExit</key>\n      <false/>\n    </dict>"),
        ("ThrottleInterval", "<integer>10</integer>"),
        (
            "WorkingDirectory",
            f"<string>{_xml(_working_directory(request, executable))}</string>",
        ),
        ("ProcessType", "<string>Background</string>"),
    ]
    if request.log_file is not None:
        entries.append(("StandardOutPath", f"<string>{_xml(request.log_file)}</string>"))
        entries.append(("StandardErrorPath", f"<string>{_xml(request.log_file)}</string>"))

    body = "\n".join(f"    <key>{key}</key>\n    {value}" for key, value in entries)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "  <dict>\n"
        f"{body}\n"
        "  </dict>\n"
        "</plist>\n"
    )
    return ServiceDefinition(
        platform="macos",
        scope=scope,
        path=plist_path,
        content=content,
        install_commands=(("launchctl", "load", "-w", str(plist_path)),),
        uninstall_commands=(("launchctl", "unload", "-w", str(plist_path)),),
        status_commands=(("launchctl", "list", LAUNCHD_LABEL),),
        environment_path=env_path,
        environment_content=f"{TOKEN_ENV_VAR}={request.token}\n" if request.token else "",
        notes=_notes(request, f"log show --predicate 'process == \"{executable.name}\"'"),
    )


def _scheduled_task(request: ServiceRequest, executable: PurePath) -> ServiceDefinition:
    """A per-user scheduled task, registered to run at logon.

    Deliberately not a Windows Service. The standalone sidecar is a console executable
    with no service-control handshake, and shipping a shim to fake one would be a second
    supervisor — the exact thing this module refuses to become. A logon task is honest
    about what it is, needs no privileges, and is what most operators want anyway; anyone
    who genuinely needs a boot-time service can wrap it with a third-party tool, which is
    then theirs to maintain.
    """
    root = (
        request.root
        if request.root is not None
        else _flavoured(
            request,
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")),
        )
    )
    task_path = root / "AnyInfer" / f"{SERVICE_NAME}.xml"
    arguments = " ".join(_windows_arg(a) for a in request.server_arguments)
    logon = (
        "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
        if request.scope == "user"
        else "<BootTrigger><Enabled>true</Enabled></BootTrigger>"
    )
    content = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.4" '
        'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>AnyInfer OpenAI-compatible sidecar</Description>\n"
        f"    <URI>\\{TASK_NAME}</URI>\n"
        "  </RegistrationInfo>\n"
        f"  <Triggers>{logon}</Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>\n"
        "    <Enabled>true</Enabled>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{_xml(executable)}</Command>\n"
        f"      <Arguments>{_xml(arguments)}</Arguments>\n"
        f"      <WorkingDirectory>{_xml(_working_directory(request, executable))}"
        "</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )
    notes = list(_notes(request, "Task Scheduler > Task Scheduler Library, or --log-file"))
    if request.token:
        # No environment file here. A file mode is close to meaningless on Windows, and a
        # weakly-protected secret file that looks protected is worse than telling the
        # operator to put the value where the OS already guards it.
        notes.insert(
            0,
            f"set the bearer token as a user environment variable before the task runs: "
            f"setx {TOKEN_ENV_VAR} <token>  (the task inherits it at logon; AnyInfer will "
            f"not write a token file on Windows)",
        )
    return ServiceDefinition(
        platform="windows",
        scope=request.scope,
        path=task_path,
        content=content,
        encoding="utf-16",
        install_commands=(
            ("schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(task_path), "/F"),
            ("schtasks", "/Run", "/TN", TASK_NAME),
        ),
        uninstall_commands=(("schtasks", "/Delete", "/TN", TASK_NAME, "/F"),),
        status_commands=(("schtasks", "/Query", "/TN", TASK_NAME),),
        notes=tuple(notes),
    )


def _notes(request: ServiceRequest, log_hint: str) -> tuple[str, ...]:
    """Operator-facing facts the definition file cannot state for itself."""
    notes = [f"logs: {log_hint}"]
    if request.log_file is not None:
        notes.append(
            f"AnyInfer writes {request.log_file} and never rotates it — that is the "
            "platform's job or yours"
        )
    if request.token:
        notes.append(
            f"the token is read from {TOKEN_ENV_VAR}; it is never written into the "
            "service definition"
        )
    if request.host not in (_LOOPBACK, "localhost"):
        notes.append(
            f"this service listens on {request.host}, not loopback: every configured "
            "provider is reachable by anyone who can reach that address with the token"
        )
    return tuple(notes)


def _xml(value: object) -> str:
    """Escape a value for XML character data."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _windows_arg(value: str) -> str:
    """Quote one argument for a scheduled task's command line."""
    return f'"{value}"' if " " in value else value
