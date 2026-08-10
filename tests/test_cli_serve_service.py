"""``anyinfer serve install / uninstall / status`` (SI.2).

No test installs anything into a developer's real systemd, launchd, or Task Scheduler: the
definition path is redirected under ``tmp_path`` and the command runner is replaced, so
what is asserted is *what would be run* rather than the effect of running it.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath, WindowsPath

import pytest

from anyinfer import cli
from anyinfer.cli import main
from anyinfer.serve import service as service_module


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Record the service-manager commands instead of running them."""
    ran: list[tuple[str, ...]] = []

    def record(command: tuple[str, ...]) -> tuple[int, str]:
        ran.append(command)
        return 0, ""

    monkeypatch.setattr(cli, "_run_command", record)
    return ran


@pytest.fixture(autouse=True)
def _under_a_temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Render every definition into the test's own directory.

    The request carries its root as data precisely so this is possible; without it a test
    run would write into the developer's real service directories. The *platform* is
    pinned to Linux so the command behaviour is asserted against one shape everywhere —
    the definitions themselves are covered per-platform in `test_serve_service`. The
    root keeps the host's path flavour, so the paths written are real native paths.
    """
    flavour = PureWindowsPath if isinstance(tmp_path, WindowsPath) else PurePosixPath
    root = flavour(str(tmp_path / "root"))

    def rooted(args: object) -> service_module.ServiceRequest:
        config = getattr(args, "config", None)
        return service_module.ServiceRequest(
            executable=PurePosixPath("/opt/anyinfer/anyinfer"),
            arguments=("serve",),
            config=Path(config).resolve() if config else None,
            host=getattr(args, "host", "127.0.0.1"),
            port=getattr(args, "port", 8080),
            expose=tuple(getattr(args, "expose", ()) or ()),
            allow_remote_exposure=bool(getattr(args, "allow_remote_exposure", False)),
            token=getattr(args, "token", None),
            log_file=getattr(args, "log_file", None),
            scope="system" if getattr(args, "system", False) else "user",
            platform="linux",
            root=root,
        )

    monkeypatch.setattr(cli, "_service_request", rooted)


def _unit(tmp_path: Path) -> Path:
    return tmp_path / "root/.config/systemd/user/anyinfer-serve.service"


# ---- serve keeps working -------------------------------------------------------------


def test_serve_without_a_subcommand_still_means_run_the_server() -> None:
    """The verb everything else documents must not have been turned into a group."""
    args = cli.build_parser().parse_args(["serve", "--port", "9001"])
    assert getattr(args, "serve_command", None) is None
    assert args.port == 9001


# ---- install ---------------------------------------------------------------------------


def test_print_writes_nothing_and_runs_nothing(
    tmp_path: Path, commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "install", "--print"]) == 0

    out = capsys.readouterr().out
    assert "[Unit]" in out
    assert "systemctl --user daemon-reload" in out
    assert commands == []
    assert not _unit(tmp_path).exists()


def test_install_writes_then_registers(
    tmp_path: Path, commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "install", "--yes", "--no-verify"]) == 0

    assert _unit(tmp_path).read_text(encoding="utf-8").startswith("[Unit]")
    assert commands == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "anyinfer-serve.service"),
    ]
    assert "wrote" in capsys.readouterr().out


def test_an_existing_definition_is_refused(
    tmp_path: Path, commands: list[tuple[str, ...]]
) -> None:
    assert main(["serve", "install", "--yes", "--no-verify"]) == 0
    original = _unit(tmp_path).read_text(encoding="utf-8")
    commands.clear()

    assert main(["serve", "install", "--yes", "--no-verify"]) == 1
    assert _unit(tmp_path).read_text(encoding="utf-8") == original
    assert commands == [], "a refusal registers nothing"

    assert main(["serve", "install", "--yes", "--no-verify", "--force"]) == 0
    assert commands


def test_system_scope_prints_rather_than_elevating(
    tmp_path: Path, commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    """R-SI3: a library CLI that shells into sudo is not something to ship."""
    assert main(["serve", "install", "--system", "--yes", "--no-verify"]) == 0

    out = capsys.readouterr().out
    assert "run these as root" in out
    assert commands == []
    assert not any(tmp_path.rglob("anyinfer-serve.service"))


def test_a_token_never_reaches_the_terminal(
    tmp_path: Path, commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "tok-should-be-redacted"
    assert main(["serve", "install", "--print", "--token", secret]) == 0
    assert secret not in capsys.readouterr().out


def test_a_token_lands_only_in_the_private_file(
    tmp_path: Path, commands: list[tuple[str, ...]]
) -> None:
    secret = "tok-on-disk-once"
    assert main(["serve", "install", "--yes", "--no-verify", "--token", secret]) == 0

    assert secret not in _unit(tmp_path).read_text(encoding="utf-8")
    env_file = tmp_path / "root/.config/anyinfer/serve.env"
    assert env_file.read_text(encoding="utf-8") == f"ANYINFER_SERVE_TOKEN={secret}\n"


def test_a_non_loopback_install_without_a_token_is_refused(
    commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(
        ["serve", "install", "--host", "0.0.0.0", "--allow-remote-exposure", "--print"]
    ) == 1
    assert "bearer token" in capsys.readouterr().err
    assert commands == []


def test_a_failing_manager_leaves_the_file_but_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_run_command", lambda command: (1, "Failed to connect to bus"))

    assert main(["serve", "install", "--yes", "--no-verify"]) == 1
    assert _unit(tmp_path).exists()
    assert "written but not registered" in " ".join(capsys.readouterr().err.split())


# ---- uninstall ---------------------------------------------------------------------------


def test_uninstall_deregisters_and_deletes(
    tmp_path: Path, commands: list[tuple[str, ...]]
) -> None:
    assert main(["serve", "install", "--yes", "--no-verify", "--token", "tok"]) == 0
    commands.clear()

    assert main(["serve", "uninstall", "--yes"]) == 0
    assert commands == [
        ("systemctl", "--user", "disable", "--now", "anyinfer-serve.service"),
        ("systemctl", "--user", "daemon-reload"),
    ]
    assert not _unit(tmp_path).exists()
    assert not (tmp_path / "root/.config/anyinfer/serve.env").exists()


def test_uninstalling_what_was_never_installed_says_so(
    commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "uninstall", "--yes"]) == 0
    assert "not present" in capsys.readouterr().out


# ---- status --------------------------------------------------------------------------------


def test_status_reports_absence_with_a_nonzero_exit(
    commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "status"]) == 1
    assert "installed  no" in capsys.readouterr().out


def test_status_is_read_only(
    tmp_path: Path, commands: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "install", "--yes", "--no-verify"]) == 0
    commands.clear()

    assert main(["serve", "status"]) == 0
    assert commands == [("systemctl", "--user", "status", "anyinfer-serve.service",
                         "--no-pager")]
    assert "installed  yes" in capsys.readouterr().out
