"""A fresh .NET application follows the written C# installation and quickstart steps.

The commands come from the Markdown pages themselves, so a page edit that breaks the steps fails
here. The offline step needs no network or credentials; the local-server step talks only to a
loopback stand-in for an OpenAI-compatible server such as Ollama or LM Studio.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLATION = ROOT / "docs" / "guides" / "csharp-installation.md"
QUICKSTART = ROOT / "docs" / "guides" / "csharp-quickstart.md"
PLACEHOLDERS = {"<your-app>", "<checkout>"}
OFFLINE_OUTPUT = "Mars (9 input + 1 output tokens)"
PROMPT = "Name one planet in the solar system."
SNIPPET = re.compile(
    r'^\s*--8<--\s+"examples/csharp-sdk/(?P<file>[A-Za-z]+\.cs)(?::[a-z-]+)?"\s*$'
)


def section(page: Path, heading: str) -> str:
    """Return the body of the ``##`` section titled ``heading``."""
    text = page.read_text(encoding="utf-8")
    match = re.search(
        rf"^## {re.escape(heading)}(?: \{{#[^}}]+\}})?\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{page.name} has no '{heading}' section"
    return match.group("body")


def bash_block(page: Path, heading: str) -> str:
    """Return the single bash block a page shows under ``heading``."""
    blocks = re.findall(r"^```bash\n(.*?)^```", section(page, heading), re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1, f"{page.name} '{heading}' must show exactly one bash block"
    return str(blocks[0])


def substitute(block: str, app: Path) -> str:
    """Replace the documented placeholders with the temporary app and this checkout."""
    found = set(re.findall(r"<[a-z-]+>", block))
    assert found <= PLACEHOLDERS, f"undocumented placeholders {sorted(found - PLACEHOLDERS)}"
    return block.replace("<your-app>", app.as_posix()).replace("<checkout>", ROOT.as_posix())


def environment() -> dict[str, str]:
    """Return a quiet .NET environment that never routes loopback through a proxy."""
    env = dict(os.environ)
    env.update(
        DOTNET_NOLOGO="1",
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
        DOTNET_CLI_USE_MSBUILD_SERVER="0",
        MSBUILDDISABLENODEREUSE="1",
    )
    for name in ("NO_PROXY", "no_proxy"):
        env[name] = ",".join(filter(None, (env.get(name), "127.0.0.1", "localhost")))
    return env


def run_bash(script: str, cwd: Path) -> str:
    """Run a documented block as one bash script and return its standard output."""
    completed = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=cwd,
        env=environment(),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert completed.returncode == 0, (
        f"documented steps failed ({completed.returncode}):\n{script}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    return completed.stdout


class _CompatServer(BaseHTTPRequestHandler):
    """Answers chat completions the way an OpenAI-compatible loopback server does."""

    seen: list[dict[str, object]]

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "model": body.get("model"),
                "prompt": body["messages"][0]["content"],
            }
        )
        payload = json.dumps(
            {
                "choices": [{"message": {"content": "Saturn"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output free of per-request access logs."""


@pytest.fixture
def compat_server() -> Iterator[tuple[str, list[dict[str, object]]]]:
    """Serve an OpenAI-compatible stand-in on an ephemeral loopback port."""
    seen: list[dict[str, object]] = []
    handler = type("CompatServer", (_CompatServer,), {"seen": seen})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _require_dotnet8() -> None:
    if sys.platform == "win32" or shutil.which("bash") is None:
        pytest.skip("the documented steps are bash commands")
    if shutil.which("dotnet") is None:
        pytest.skip("the .NET SDK is not installed")
    runtimes = subprocess.run(
        ["dotnet", "--list-runtimes"], capture_output=True, text=True, check=False
    ).stdout
    if "Microsoft.NETCore.App 8." not in runtimes:
        pytest.skip("the .NET 8 runtime the C# SDK targets is not installed")


def test_the_quickstart_copies_exactly_the_example_files_it_shows() -> None:
    shown = {
        match.group("file")
        for line in QUICKSTART.read_text(encoding="utf-8").splitlines()
        if (match := SNIPPET.match(line))
    }
    copied = set(
        re.findall(
            r'^cp "<checkout>/examples/csharp-sdk/([A-Za-z]+\.cs)" \.$',
            bash_block(QUICKSTART, "Test without a network or key"),
            re.MULTILINE,
        )
    )
    assert copied == shown == {"QuickstartExample.cs", "QuickstartTestingExample.cs"}
    assert f"It prints `{OFFLINE_OUTPUT}`" in QUICKSTART.read_text(encoding="utf-8")


@pytest.mark.slow
def test_a_fresh_application_follows_the_installation_and_quickstart_pages(
    tmp_path: Path, compat_server: tuple[str, list[dict[str, object]]]
) -> None:
    _require_dotnet8()
    app = tmp_path / "Quickstart App"

    run_bash(substitute(bash_block(INSTALLATION, "Add a project reference"), app), tmp_path)
    project = (app / "Quickstart App.csproj").read_text(encoding="utf-8")
    assert "<TargetFramework>net8.0</TargetFramework>" in project
    assert "src" in project and "AnyInfer.csproj" in project

    offline = run_bash(
        substitute(bash_block(QUICKSTART, "Test without a network or key"), app), app
    )
    assert offline.strip().splitlines()[-1] == OFFLINE_OUTPUT

    # The same copied example calls a keyless OpenAI-compatible server on loopback.
    base_url, seen = compat_server
    (app / "Program.cs").write_text(
        "using AnyInfer.Examples;\n"
        f'var settings = QuickstartExample.LocalServer("{base_url}");\n'
        'var result = await QuickstartExample.FirstCallAsync(settings, "openai-compat:qwen3:8b");\n'
        "Console.WriteLine(QuickstartExample.Describe(result));\n",
        encoding="utf-8",
    )
    local = run_bash("dotnet run", app)
    assert local.strip().splitlines()[-1] == "Saturn (4 input + 2 output tokens)"
    assert seen == [
        {
            "path": "/v1/chat/completions",
            "authorization": None,
            "model": "qwen3:8b",
            "prompt": PROMPT,
        }
    ]
