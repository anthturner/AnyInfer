"""Tests for the developer task runner.

The runner is what contributors touch first, so its argument handling is tested rather than
assumed. Nothing here spawns a subprocess: verbs are dispatched with the process helpers
patched out, so the suite stays fast and never actually runs pytest inside pytest.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import workspace  # noqa: E402


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture what a verb would run, instead of running it.

    The docs gates are in-process functions rather than subprocesses, so they are
    patched to record sentinels in the same stream — the suite must never depend on the
    repository's actual docs health.
    """
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return 0

    monkeypatch.setattr(workspace, "run", fake_run)
    monkeypatch.setattr(
        workspace, "_check_docstrings", lambda: commands.append(["<docstrings>"]) or 0
    )
    monkeypatch.setattr(
        workspace, "_check_doc_links", lambda: commands.append(["<doc-links>"]) or 0
    )
    return commands


class TestRegistry:
    def test_every_verb_has_a_summary_and_a_docstring(self):
        for name, entry in workspace.REGISTRY.items():
            assert entry.summary, f"{name} has no summary"
            assert entry.handler.__doc__, f"{name} has no docstring"

    def test_the_verbs_the_request_named_all_exist(self):
        for name in ("build", "clean", "demo", "check", "web"):
            assert name in workspace.REGISTRY

    def test_the_absorbed_verbs_are_gone(self):
        """The old standalone gates live inside `check` (and `build docs`) now."""
        for name in ("lint", "format", "types", "contracts", "test", "conformance",
                     "docs-check", "docs-build"):
            assert name not in workspace.REGISTRY

    def test_help_lists_every_registered_verb(self):
        epilog = workspace._epilog()
        for name in workspace.REGISTRY:
            assert name in epilog

    def test_bare_invocation_prints_help_and_succeeds(self, capsys):
        assert workspace.main([]) == 0
        assert "verbs:" in capsys.readouterr().out

    def test_every_group_has_an_icon_in_the_help(self):
        epilog = workspace._epilog()
        for group in workspace.GROUP_ORDER:
            assert workspace.GROUP_ICONS[group].strip() in epilog


class TestPassthrough:
    def test_forwards_flags_to_the_wrapped_tool(self):
        own, rest = workspace._split_passthrough(["serve", "--port", "9", "-v"])
        assert own == ["serve"]
        assert rest == ["--port", "9", "-v"]

    def test_forwards_help_rather_than_intercepting_it(self):
        """`workspace demo --help` must show the demo's help, not the runner's."""
        own, rest = workspace._split_passthrough(["demo", "--help"])
        assert own == ["demo"]
        assert rest == ["--help"]

    def test_a_bare_double_dash_is_consumed_once(self):
        own, rest = workspace._split_passthrough(["serve", "--", "--fix"])
        assert own == ["serve"]
        assert rest == ["--fix"]

    def test_non_passthrough_verbs_keep_their_own_flags(self):
        own, rest = workspace._split_passthrough(["clean", "--all"])
        assert own == ["clean", "--all"]
        assert rest == []

    def test_unknown_verbs_are_left_for_argparse_to_reject(self):
        own, rest = workspace._split_passthrough(["nonsense", "--x"])
        assert own == ["nonsense", "--x"]
        assert rest == []


class TestVerbs:
    def test_check_only_test_runs_pytest_headless(self, recorded, monkeypatch):
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        assert workspace.main(["check", "--only=test"]) == 0
        assert any("pytest" in part for part in recorded[0])
        assert workspace._headless_env()["QT_QPA_PLATFORM"] == "offscreen"

    def test_check_only_lint_covers_the_runner_itself(self, recorded):
        workspace.main(["check", "--only=lint"])
        assert "workspace.py" in recorded[0]

    def test_check_fix_reaches_the_lint_phase(self, recorded):
        workspace.main(["check", "--only=lint", "--fix"])
        assert "--fix" in recorded[0]

    def test_check_runs_every_default_gate_in_order(self, recorded):
        assert workspace.main(["check"]) == 0
        # `tool()` resolves executables to absolute paths, so match on basename + argv.
        def position(name: str, subcommand: str | None = None) -> int:
            return next(
                i for i, cmd in enumerate(recorded)
                if name in Path(cmd[0]).name.lower()
                and (subcommand is None or (len(cmd) > 1 and cmd[1] == subcommand))
            )

        # Fastest-feedback-first: static analysis, types, contracts, then the suites,
        # then the docs gates and the artifact build the deploy publishes.
        # The docs gates are the in-process sentinels the `recorded` fixture plants.
        positions = [
            position("ruff", "check"),
            position("mypy"),
            position("lint-imports"),
            position("pytest"),
            recorded.index(["<docstrings>"]),
            recorded.index(["<doc-links>"]),
            position("mkdocs", "build"),
        ]
        assert positions == sorted(positions), "phases must run in the documented order"
        # The formatter is the one gate that stays opt-in.
        assert not any(len(cmd) > 1 and cmd[1] == "format" for cmd in recorded)

    def test_check_covers_every_gate_ci_enforces(self, recorded):
        """`check` is the whole pipeline: no CI job may run a gate it cannot reproduce.

        The workflow reaches every gate through `check --only=<phase>`, so the phases the
        workflow names and the phases the runner knows must be the same set — otherwise a
        contributor's green `check` is a weaker claim than a green CI run.
        """
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        invoked = set(re.findall(r"workspace\.py check --only=(\S+)", workflow))
        assert invoked, "CI must drive the gates through `workspace check`"
        assert invoked <= set(workspace.GATE_ORDER), "CI names a phase the runner lacks"
        assert set(workspace.DEFAULT_GATES) <= invoked, "a default gate is not enforced by CI"
        assert not re.search(r"run: python workspace\.py (?!check|build docs)", workflow), (
            "CI must not run a gate outside `workspace check`"
        )

    def test_pages_deploy_isolated_from_reruns_and_upload_retries(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
            encoding="utf-8"
        )
        artifact_name = "github-pages-${{ github.run_id }}-${{ github.run_attempt }}"

        assert f"PAGES_ARTIFACT_NAME: {artifact_name}" in workflow
        assert workflow.count("actions: write") == 1
        assert "KEEP_ARTIFACT_ID: ${{ steps.pages-artifact.outputs.artifact_id }}" in workflow
        assert "(.id | tostring) != $keep" in workflow
        assert "gh api --method DELETE" in workflow
        assert "artifact_name: ${{ env.PAGES_ARTIFACT_NAME }}" in workflow

    def test_check_announces_each_phase_with_a_heading(self, recorded, capsys):
        assert workspace.main(["check"]) == 0
        output = capsys.readouterr().out
        for phase in workspace.DEFAULT_GATES:
            assert f"phase: {phase}" in output

    def test_check_only_format_runs_the_formatter(self, recorded):
        assert workspace.main(["check", "--only=format"]) == 0
        assert recorded[0][1:3] == ["format", "--check"]

    def test_check_skip_and_only_are_mutually_exclusive(self):
        with pytest.raises(SystemExit) as caught:
            workspace.main(["check", "--only=lint", "--skip=types"])
        assert caught.value.code != 0

    def test_check_rejects_unknown_phases_with_the_valid_list(self, capsys):
        assert workspace.main(["check", "--only=bogus"]) == 1
        output = capsys.readouterr().out
        assert "bogus" in output
        assert "lint" in output, "the error must teach the valid phase names"

    def test_check_skip_leaves_the_named_phases_out(self, recorded):
        assert workspace.main(["check", "--skip=test,conformance,docs-check"]) == 0
        names = [Path(cmd[0]).name.lower() for cmd in recorded]
        assert not any("pytest" in name for name in names)
        assert any("ruff" in name for name in names)
        assert any("mypy" in name for name in names)

    def test_check_reports_failures_without_stopping(self, monkeypatch, capsys):
        """A failing phase must not hide the phases after it."""
        calls: list[str] = []

        def failing_run(command, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(command[0])
            return 0 if "mypy" not in command[0] else 1

        monkeypatch.setattr(workspace, "run", failing_run)
        monkeypatch.setattr(
            workspace, "_check_docstrings", lambda: calls.append("docstrings") or 0
        )
        monkeypatch.setattr(
            workspace, "_check_doc_links", lambda: calls.append("doc-links") or 0
        )
        assert workspace.main(["check"]) == 1

        output = capsys.readouterr().out
        assert "FAIL" in output and "PASS" in output
        # The seven default phases comprise ten steps — eight subprocesses plus the two
        # in-process docs gates; every one must have been attempted despite the failure
        # (conformance has two steps, docs-check three).
        assert len(calls) == 10

    def test_build_docs_builds_the_exact_pages_artifact(self, recorded):
        assert workspace.main(["build", "docs"]) == 0
        assert recorded[0][1:] == ["build", "--strict"]
        assert "mkdocs" in recorded[0][0]

    def test_web_verb_builds_strictly_then_serves_loopback_only(self, recorded, capsys):
        """`workspace web` previews the exact Pages artifact: strict build, then serve."""
        assert workspace.main(["web", "--port", "9999"]) == 0

        build, serve = recorded
        assert "mkdocs" in build[0] and build[1:] == ["build", "--strict"]
        assert serve[-6:] == ["http.server", "9999", "--directory", "site",
                              "--bind", "127.0.0.1"]
        assert "http://127.0.0.1:9999/" in capsys.readouterr().out

    def test_demo_verb_reports_a_missing_pyside(self, monkeypatch, capsys):
        """The failure must name the fix, not surface an ImportError traceback."""
        import importlib.util

        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name, *args, **kwargs):
            return None if name == "PySide6" else real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

        assert workspace.main(["demo"]) == 1
        assert "PySide6 is not installed" in capsys.readouterr().out


class TestBuild:
    """Native and platform-independent build dispatch."""

    @pytest.fixture
    def built(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Record which builders run, instead of running PyInstaller in the suite."""
        calls: list[str] = []
        monkeypatch.setattr(workspace, "_build_wheel", lambda: calls.append("wheel") or 0)
        monkeypatch.setattr(
            workspace, "_build_demo_bundle", lambda: calls.append("demo") or 0
        )
        monkeypatch.setattr(
            workspace, "_build_serve_bundle", lambda: calls.append("serve") or 0
        )
        return calls

    def test_the_bundle_demo_verb_is_gone(self):
        assert "bundle-demo" not in workspace.REGISTRY

    def test_default_builds_the_wheel(self, built):
        assert workspace.main(["build"]) == 0
        assert built == ["wheel"]

    def test_demo_targets_this_machine_by_default(self, built):
        assert workspace.main(["build", "demo"]) == 0
        assert built == ["demo"]

    def test_sidecar_targets_this_machine_by_default(self, built):
        assert workspace.main(["build", "serve"]) == 0
        assert built == ["serve"]

    def test_all_builds_wheel_then_both_native_bundles(self, built):
        assert workspace.main(["build", "all"]) == 0
        assert built == ["wheel", "demo", "serve"]

    def test_the_wheel_is_platform_independent(self, built):
        """A pure-Python wheel serves every platform, so any platform argument works."""
        for requested in ("windows", "macos", "linux", "all"):
            assert workspace.main(["build", "wheel", requested]) == 0
        assert built == ["wheel"] * 4

    def test_all_platforms_builds_the_host_and_skips_the_rest(self, built, capsys):
        assert workspace.main(["build", "demo", "all"]) == 0
        assert built == ["demo"], "only the host platform is buildable locally"
        assert "release workflow" in capsys.readouterr().out

        built.clear()
        assert workspace.main(["build", "serve", "all"]) == 0
        assert built == ["serve"], "only the host platform is buildable locally"
        assert "release workflow" in capsys.readouterr().out

    def test_a_foreign_demo_platform_is_refused_with_the_ci_path(self, built, capsys):
        """Asking for exactly one platform this machine cannot build must fail loudly."""
        host = workspace._host_platform()
        other = next(p for p in ("windows", "macos", "linux") if p != host)

        assert workspace.main(["build", "demo", other]) == 1
        assert built == []
        assert "release.yml" in capsys.readouterr().out

    def test_an_unknown_target_is_rejected(self):
        with pytest.raises(SystemExit) as caught:
            workspace.build_parser().parse_args(["build", "nonsense"])
        assert caught.value.code != 0

    def test_sidecar_stub_defaults_to_the_serve_subcommand(self):
        assert 'main(["serve", *sys.argv[1:]])' in workspace._SERVE_ENTRY_STUB


class TestAbsorbedGates:
    """The first-party maintenance code that lives in the runner itself."""

    def test_doc_link_check_reports_a_broken_link(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "index.md").write_text(
            "[exists](../README.md) and [gone](missing.md)", encoding="utf-8"
        )
        (tmp_path / "README.md").write_text("# readme", encoding="utf-8")

        assert workspace._check_doc_links() == 1
        assert "missing.md" in capsys.readouterr().err

    def test_doc_link_check_accepts_external_and_anchor_links(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        (tmp_path / "index.md").write_text(
            "[web](https://example.com) [mail](mailto:x@y.z) [top](#heading)",
            encoding="utf-8",
        )

        assert workspace._check_doc_links() == 0

    def test_doc_link_check_skips_generated_directories(self, tmp_path, monkeypatch):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        generated = tmp_path / "site"
        generated.mkdir()
        (generated / "page.md").write_text("[gone](missing.md)", encoding="utf-8")

        assert workspace._check_doc_links() == 0

    def test_docstring_check_passes_on_the_real_package(self, capsys):
        """The gate the docs build depends on holds for the installed package."""
        assert workspace._check_docstrings() == 0
        assert "documented" in capsys.readouterr().out

    def test_bundle_platform_tag_is_os_dash_arch(self):
        import re

        assert re.fullmatch(r"(windows|macos|linux)-[a-z0-9_]+",
                            workspace._bundle_platform_tag())


class TestClean:
    def test_dry_run_removes_nothing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        target = tmp_path / "dist"
        target.mkdir()

        workspace.main(["clean", "--dry-run"])

        assert target.exists(), "--dry-run must not delete anything"
        assert "would remove" in capsys.readouterr().out

    def test_removes_build_outputs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        target = tmp_path / "dist"
        target.mkdir()
        (target / "wheel.whl").write_text("x", encoding="utf-8")

        assert workspace.main(["clean"]) == 0
        assert not target.exists()

    def test_keeps_caches_unless_all_is_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        cache = tmp_path / ".mypy_cache"
        cache.mkdir()

        workspace.main(["clean"])
        assert cache.exists(), "caches survive a plain clean"

        workspace.main(["clean", "--all"])
        assert not cache.exists()

    def test_never_touches_source_or_virtualenvs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(workspace, "ROOT", tmp_path)
        source = tmp_path / "src" / "anyinfer"
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("x", encoding="utf-8")
        venv_cache = tmp_path / ".venv" / "lib" / "__pycache__"
        venv_cache.mkdir(parents=True)

        workspace.main(["clean", "--all"])

        assert (source / "__init__.py").exists(), "source must never be removed"
        assert venv_cache.exists(), "a virtualenv is not ours to sweep"


class TestRepositoryRoot:
    def test_the_checkout_is_found_from_the_repository(self):
        assert (workspace.ROOT / "pyproject.toml").exists()
        assert (workspace.ROOT / "src" / "anyinfer").is_dir()

    def test_a_directory_without_the_markers_is_not_a_checkout(
        self, tmp_path, monkeypatch
    ):
        """With the module outside a checkout too, nothing is found.

        This is the case that matters for the installed console script, run from a
        directory unrelated to any checkout.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(workspace, "__file__", str(tmp_path / "workspace.py"))
        monkeypatch.setattr(workspace, "REPO_MARKERS", ("marker-that-cannot-exist",))
        assert workspace._find_repository_root() is None

    def test_the_module_directory_is_the_fallback(self, tmp_path, monkeypatch):
        """`python /path/to/repo/workspace.py` from an unrelated cwd still finds it."""
        monkeypatch.chdir(tmp_path)
        assert workspace._find_repository_root() == workspace.ROOT

    def test_a_subdirectory_resolves_to_the_checkout(self, monkeypatch):
        """Running from `src/` or `docs/` must still find the repository root."""
        monkeypatch.chdir(workspace.ROOT / "src")
        assert workspace._find_repository_root() == workspace.ROOT

    def test_running_outside_a_checkout_refuses_with_a_reason(
        self, tmp_path, monkeypatch, capsys
    ):
        """Gates must not run against site-packages and emit a screenful of noise."""
        monkeypatch.setattr(workspace, "_ROOT", None)

        assert workspace.main(["check"]) == 2
        assert "no AnyInfer checkout found" in capsys.readouterr().out


class TestShadowing:
    def test_the_repository_copy_is_not_reported_as_stale(self):
        assert workspace._warn_if_shadowed() is None

    def test_a_differing_installed_copy_is_reported(self, tmp_path, monkeypatch):
        """A stale installed copy silently ignoring your edits is the worst outcome."""
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        (checkout / "workspace.py").write_text("# the edited version\n", encoding="utf-8")

        installed = tmp_path / "site-packages" / "workspace.py"
        installed.parent.mkdir()
        installed.write_text("# the stale version\n", encoding="utf-8")

        monkeypatch.setattr(workspace, "ROOT", checkout)
        monkeypatch.setattr(workspace, "__file__", str(installed))

        message = workspace._warn_if_shadowed()
        assert message is not None
        assert "pip install -e ." in message

    def test_an_identical_installed_copy_is_not_reported(self, tmp_path, monkeypatch):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        (checkout / "workspace.py").write_text("# same\n", encoding="utf-8")

        installed = tmp_path / "site-packages" / "workspace.py"
        installed.parent.mkdir()
        installed.write_text("# same\n", encoding="utf-8")

        monkeypatch.setattr(workspace, "ROOT", checkout)
        monkeypatch.setattr(workspace, "__file__", str(installed))

        assert workspace._warn_if_shadowed() is None


class TestProcessHelpers:
    def test_missing_tool_gives_an_actionable_error(self, monkeypatch, capsys):
        def missing(command, cwd=None, env=None, check=False):  # type: ignore[no-untyped-def]
            raise FileNotFoundError(command[0])

        monkeypatch.setattr(workspace.subprocess, "run", missing)
        assert workspace.main(["check", "--only=types"]) == 1
        assert "workspace setup" in capsys.readouterr().out

    def test_colors_are_suppressed_when_not_a_tty(self, monkeypatch):
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert workspace.green("ok") == "ok"

    def test_headless_env_bypasses_the_hardware_cache(self):
        assert workspace._headless_env()["ANYINFER_HARDWARE_CACHE_BYPASS"] == "1"


class TestParser:
    def test_every_verb_builds_a_subparser(self):
        parser = workspace.build_parser()
        for name in workspace.REGISTRY:
            assert parser.parse_args([name]) is not None

    def test_unknown_verb_exits_nonzero(self):
        with pytest.raises(SystemExit) as caught:
            workspace.build_parser().parse_args(["nonsense"])
        assert caught.value.code != 0

    def test_describe_strips_rst_markup(self):
        def handler(args: argparse.Namespace) -> int:
            """Summary line.

            Body mentioning ``code``.
            """
            return 0

        described = workspace._describe(handler)
        assert "``" not in described
        assert described.startswith("Summary line.")
