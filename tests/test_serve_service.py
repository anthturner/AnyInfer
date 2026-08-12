"""Service definitions for the sidecar (SI.1, SI.3, SI.4).

Rendering is pure, so all three platforms' definitions are exercised from whichever one
this suite happens to run on. Nothing here touches a real systemd, launchd, or Task
Scheduler: every path is built under a temp root the request carries as data.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from anyinfer.errors import ConfigError
from anyinfer.serve.service import (
    LAUNCHD_LABEL,
    SERVICE_NAME,
    TASK_NAME,
    TOKEN_ENV_VAR,
    ServicePlatform,
    ServiceRequest,
    render_service,
    resolve_executable,
    write_service,
)

PLATFORMS: tuple[ServicePlatform, ...] = ("linux", "macos", "windows")

_EXECUTABLES: dict[str, object] = {
    "linux": PurePosixPath("/opt/anyinfer/anyinfer"),
    "macos": PurePosixPath("/opt/anyinfer/anyinfer"),
    "windows": PureWindowsPath(r"C:\Program Files\AnyInfer\anyinfer.exe"),
}

_ROOTS: dict[str, object] = {
    "linux": PurePosixPath("/home/operator"),
    "macos": PurePosixPath("/Users/operator"),
    "windows": PureWindowsPath(r"C:\Users\operator\AppData\Local"),
}


def _request(platform: ServicePlatform, **overrides: object) -> ServiceRequest:
    fields: dict[str, object] = {
        "executable": _EXECUTABLES[platform],
        "arguments": ("serve",),
        "platform": platform,
        "root": _ROOTS[platform],
    }
    fields.update(overrides)
    return ServiceRequest(**fields)  # type: ignore[arg-type]


# ---- every platform, every time --------------------------------------------------------


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_token_never_appears_in_the_definition(platform: ServicePlatform) -> None:
    """R-SI2: a secret in a file that looks like configuration is how it gets committed."""
    secret = "tok-do-not-embed-me"
    definition = render_service(_request(platform, token=secret))

    assert secret not in definition.content
    assert TOKEN_ENV_VAR in "\n".join(definition.notes) + definition.content + str(
        definition.environment_path or ""
    )
    if definition.environment_path is not None:
        assert definition.environment_content == f"{TOKEN_ENV_VAR}={secret}\n"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_default_binds_loopback(platform: ServicePlatform) -> None:
    definition = render_service(_request(platform))
    assert "127.0.0.1" in definition.content
    assert "0.0.0.0" not in definition.content


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_executable_path_is_absolute(platform: ServicePlatform) -> None:
    definition = render_service(_request(platform))
    assert str(_EXECUTABLES[platform]) in definition.content


@pytest.mark.parametrize("platform", PLATFORMS)
def test_status_commands_are_read_only(platform: ServicePlatform) -> None:
    """The moment this issues a control verb it has become a process supervisor."""
    definition = render_service(_request(platform))
    forbidden = {"start", "stop", "restart", "enable", "disable", "load", "unload", "/Run"}
    for command in definition.status_commands:
        assert not forbidden & set(command), command


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_relative_executable_is_refused(platform: ServicePlatform) -> None:
    with pytest.raises(ConfigError, match="absolute"):
        render_service(_request(platform, executable=Path("anyinfer")))


# ---- the exposure guard ------------------------------------------------------------------


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_non_loopback_service_needs_the_exposure_flag(platform: ServicePlatform) -> None:
    """R-SI1: the worst outcome is an unauthenticated gateway that survives reboots."""
    with pytest.raises(ConfigError, match="refusing to generate"):
        render_service(_request(platform, host="0.0.0.0"))


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_non_loopback_service_needs_a_token(platform: ServicePlatform) -> None:
    with pytest.raises(ConfigError, match="bearer token"):
        render_service(_request(platform, host="0.0.0.0", allow_remote_exposure=True))


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_non_loopback_service_with_both_is_generated_and_says_so(
    platform: ServicePlatform,
) -> None:
    definition = render_service(
        _request(platform, host="10.0.0.5", allow_remote_exposure=True, token="tok")
    )
    assert "--allow-remote-exposure" in definition.content
    assert any("not loopback" in note for note in definition.notes)


# ---- per-platform shape --------------------------------------------------------------------


def test_the_systemd_unit_is_hardened() -> None:
    definition = render_service(_request("linux"))
    for directive in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
        "Restart=on-failure",
    ):
        assert directive in definition.content
    assert definition.path.name == f"{SERVICE_NAME}.service"
    assert definition.install_commands[0] == ("systemctl", "--user", "daemon-reload")


def test_the_system_scoped_unit_goes_to_etc_and_wants_multi_user() -> None:
    definition = render_service(_request("linux", scope="system"))
    assert "etc/systemd/system" in definition.path.as_posix()
    assert "WantedBy=multi-user.target" in definition.content
    assert definition.needs_elevation
    assert definition.install_commands[0] == ("systemctl", "daemon-reload")


def test_a_systemd_log_file_gets_a_writable_path() -> None:
    """`ProtectSystem=strict` makes everything read-only; the log has to be named."""
    definition = render_service(
        _request("linux", log_file=PurePosixPath("/var/log/anyinfer/serve.log"))
    )
    assert "StandardOutput=append:/var/log/anyinfer/serve.log" in definition.content
    assert "ReadWritePaths=/var/log/anyinfer" in definition.content


def test_the_launchd_agent_throttles_a_crash_loop() -> None:
    definition = render_service(_request("macos"))
    assert definition.path.name == f"{LAUNCHD_LABEL}.plist"
    assert "<key>ThrottleInterval</key>" in definition.content
    assert "<key>RunAtLoad</key>" in definition.content
    assert "/bin/sh" not in definition.content, "no wrapper is needed without a token"


def test_the_launchd_agent_sources_a_private_file_for_its_token() -> None:
    """A plist is exactly where a token must not go, and launchd has no EnvironmentFile."""
    definition = render_service(_request("macos", token="tok"))
    assert "/bin/sh" in definition.content
    assert str(definition.environment_path) in definition.content
    assert "tok" not in definition.content


def test_the_windows_task_is_a_logon_task_not_a_service() -> None:
    definition = render_service(_request("windows"))
    assert "<LogonTrigger>" in definition.content
    assert definition.encoding == "utf-16", "schtasks /XML reads UTF-16"
    assert definition.install_commands[0][:4] == ("schtasks", "/Create", "/TN", TASK_NAME)


def test_windows_declines_to_write_a_token_file_and_says_what_to_do_instead() -> None:
    """A file mode means little there; a secret file that looks protected is worse."""
    definition = render_service(_request("windows", token="tok"))
    assert definition.environment_path is None
    assert any("setx" in note for note in definition.notes)
    assert "tok" not in definition.content


# ---- executable resolution -----------------------------------------------------------------


def test_a_frozen_build_names_its_own_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The standalone entry point already means "serve", so it takes the flags directly."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(Path.cwd() / "anyinfer-serve"))

    executable, arguments = resolve_executable()
    assert arguments == ()
    assert Path(executable).is_absolute()


def test_a_temporary_executable_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A unit pointing into an extraction directory breaks on the next boot."""
    import tempfile

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(Path(tempfile.gettempdir()) / "x/anyinfer"))
    with pytest.raises(ConfigError, match="temporary directory"):
        resolve_executable()


def test_a_console_script_is_preferred_and_takes_the_serve_verb() -> None:
    executable, arguments = resolve_executable()
    assert Path(executable).is_absolute()
    assert arguments in ((), ("serve",), ("-m", "anyinfer.cli", "serve"))


# ---- writing --------------------------------------------------------------------------------


def test_writing_creates_the_definition_under_the_given_root(tmp_path: Path) -> None:
    definition = render_service(_request("linux", root=PurePosixPath(tmp_path.as_posix())))
    written = write_service(definition)

    assert written == (Path(definition.path),)
    assert Path(definition.path).read_text(encoding="utf-8").startswith("[Unit]")


def test_writing_over_an_existing_definition_is_refused(tmp_path: Path) -> None:
    definition = render_service(_request("linux", root=PurePosixPath(tmp_path.as_posix())))
    write_service(definition)

    with pytest.raises(ConfigError, match="already exists"):
        write_service(definition)
    write_service(definition, force=True)


@pytest.mark.skipif(os.name == "nt", reason="a POSIX file mode is meaningless on Windows")
def test_the_token_file_is_private(tmp_path: Path) -> None:
    """SI.4: mode 0600, and created that way rather than tightened afterwards."""
    definition = render_service(
        _request("linux", root=PurePosixPath(tmp_path.as_posix()), token="tok")
    )
    write_service(definition)

    assert definition.environment_path is not None
    mode = Path(definition.environment_path).stat().st_mode
    assert not mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH)


def test_nothing_is_written_when_one_target_already_exists(tmp_path: Path) -> None:
    """A refusal has to be total; a half-written pair is worse than neither."""
    definition = render_service(
        _request("linux", root=PurePosixPath(tmp_path.as_posix()), token="tok")
    )
    assert definition.environment_path is not None
    Path(definition.environment_path).parent.mkdir(parents=True, exist_ok=True)
    Path(definition.environment_path).write_text("keep me", encoding="utf-8")

    with pytest.raises(ConfigError, match="already exists"):
        write_service(definition)
    assert not Path(definition.path).exists()
    assert Path(definition.environment_path).read_text(encoding="utf-8") == "keep me"


# ---- the shipped instructions ----------------------------------------------------------------


def test_the_bundle_instructions_come_from_the_same_templates() -> None:
    """SI.5: the download and the command must never describe different definitions."""
    import sys as _sys
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(repo_root))
    import workspace

    executable = _Path("/opt/anyinfer-serve/anyinfer-serve").resolve()
    text = workspace.render_service_install_text(executable)
    definition = render_service(ServiceRequest(executable=executable))

    assert definition.content in text
    assert "anyinfer-serve install --print" in text
    for command in definition.install_commands:
        assert " ".join(command) in text
