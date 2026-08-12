"""Generate a working third-party provider package.

An adapter that starts from a blank file starts by reading `openai_compat.py` and guessing
which parts are contract and which are that provider's quirks. This writes the contract
part — the four methods, the descriptor, the entry point, the conformance test, and the
contract-snapshot stub, so what is left to write is the translation, which is the only
part that is actually provider knowledge.

The generated package is green out of the box. A template whose conformance run fails on
first use teaches the wrong lesson about whether the suite is worth running.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ConfigError

__all__ = ["SCAFFOLD_FILES", "scaffold_provider"]


def scaffold_provider(provider_id: str, destination: Path, *, force: bool = False) -> list[Path]:
    """Write a provider package skeleton.

    Args:
        provider_id: The provider id the adapter will register, e.g. ``acme``. Used for the
            package name, the target prefix, and the contract snapshot's filename.
        destination: Directory to write into. Created if absent.
        force: Overwrite existing files. Off by default: a scaffold that silently replaces
            an adapter someone has been writing is a scaffold nobody runs twice.

    Returns:
        The files written, in creation order.

    Raises:
        ConfigError: If the id is unusable as a Python package name, or a file exists and
            ``force`` was not passed.
    """
    normalized = provider_id.strip().lower()
    if not normalized or not normalized.replace("-", "").replace("_", "").isalnum():
        raise ConfigError(
            f"{provider_id!r} is not usable as a provider id",
            hint="use letters, digits, hyphens, and underscores",
        )

    package = f"{normalized.replace('-', '_')}_anyinfer"
    substitutions = {
        "provider_id": normalized,
        "package": package,
        # A class name and an environment-variable name, derived once so the generated
        # files cannot disagree about what this provider is called.
        "provider_id_title": "".join(
            part.capitalize() for part in normalized.replace("-", "_").split("_")
        ),
        "provider_id_upper": normalized.replace("-", "_").upper(),
    }
    written: list[Path] = []

    for relative, body in SCAFFOLD_FILES.items():
        path = destination / relative.format(**substitutions)
        if path.exists() and not force:
            raise ConfigError(
                f"{path} already exists",
                hint="pass --force to overwrite, or scaffold into an empty directory",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.format(**substitutions), encoding="utf-8")
        written.append(path)

    return written


_INIT = '''"""The {provider_id} provider for AnyInfer."""

from __future__ import annotations

from anyinfer.registry import ProviderDescriptor, ProviderSetupSpec, SetupField
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced

from .adapter import {provider_id_title}Adapter

__all__ = ["descriptor", "provider"]

descriptor = ProviderDescriptor(
    id="{provider_id}",
    display_name="{provider_id_title}",
    factory={provider_id_title}Adapter,
    # Hosted providers price their tokens; a local engine is a genuine zero.
    locality="hosted",
    default_base_url="https://api.{provider_id}.example/v1",
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=True,
                placeholder="env://{provider_id_upper}_API_KEY or a literal key",
                env_var="{provider_id_upper}_API_KEY",
            ),
            SetupField(
                key="base_url",
                label="Base URL",
                kind="endpoint",
                advanced=True,
                default_value="https://api.{provider_id}.example/v1",
            ),
        ),
    ),
    default_capabilities=ModelCapabilities(
        features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "default"),
    ),
)
"""What AnyInfer needs to know about this provider without knowing which it is."""


def provider() -> ProviderDescriptor:
    """Entry point AnyInfer calls to discover this provider."""
    return descriptor
'''

_ADAPTER = '''"""Translate AnyInfer\'s normalized request into {provider_id}\'s wire format.

An adapter *only* translates. Retry, fallback, schema validation and repair, timing, usage
normalization, telemetry, and redaction all live in AnyInfer\'s core, if you find yourself
adding control flow here, it belongs there instead.

If this provider differs from OpenAI only by endpoint, auth spelling, and quirks, do not
write an adapter at all: contribute a preset entry upstream instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from anyinfer.providers.base import AdapterEvent, ProviderConfig, WireRequest
from anyinfer.providers.http import build_client, classify_status
from anyinfer.types.capabilities import DiscoveredModel, Health

__all__ = ["{provider_id_title}Adapter"]


class {provider_id_title}Adapter:
    """The four methods every AnyInfer adapter exposes, and nothing else."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._client = build_client(config)

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Report the models this provider serves."""
        raise NotImplementedError("translate this provider's model listing")

    async def health(self) -> Health:
        """Answer a cheap readiness probe."""
        raise NotImplementedError("translate this provider's readiness check")

    def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Run one generation, yielding normalized events as they arrive.

        May be an ``async def`` generator or a plain method returning an async iterator.
        Emit `TextDelta` / `ReasoningDelta` / `ToolCallDelta` / `UsageUpdate` as they
        arrive, and finish with an `AdapterFinal`.
        """
        raise NotImplementedError("translate this provider's generation call")

    async def aclose(self) -> None:
        """Release transport resources."""
        await self._client.aclose()


# `classify_status` maps an HTTP status and its headers onto AnyInfer's typed errors,
# including Retry-After. Use it rather than raising your own exception types.
_ = classify_status
'''

_TEST = '''"""Certify this adapter against AnyInfer\'s shared conformance suite."""

from __future__ import annotations

import pytest

from anyinfer.testing.certify import load_declared_capabilities


def test_declared_capabilities_parse() -> None:
    """The [tool.anyinfer.conformance] table in pyproject.toml is readable and valid."""
    capabilities = load_declared_capabilities()
    assert isinstance(capabilities.streaming, bool)


@pytest.mark.skip(reason="implement adapter.py, then point this at a real or recorded endpoint")
async def test_conformance() -> None:
    """Run the suite once the adapter translates something.

    Replace the skip with a client factory. Against a live endpoint that means real
    credentials; against a recorded one, an `anyinfer.testing.CassetteTransport`.
    """
'''

_PYPROJECT = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{package}"
version = "0.1.0"
description = "The {provider_id} provider for AnyInfer"
requires-python = ">=3.11"
dependencies = ["anyinfer"]

# This is what makes the provider discoverable: install the package and
# `{provider_id}:model` targets resolve. The value may be a descriptor, a callable
# returning one, or an iterable of them.
[project.entry-points."anyinfer.providers"]
{provider_id} = "{package}:provider"

# Cases this adapter cannot support, declared rather than passed on a command line so the
# claim is reviewable. Every unlisted generation case defaults to supported; the
# embedding and rerank cases default to unsupported and are opted into here once the
# adapter implements the protocol and its descriptor declares the operation.
[tool.anyinfer.conformance]
# reasoning = false
# retry_after = false
# embedding = true
# rerank = true
"""

_CONTRACT = """# {provider_id} — Protocol Contract

Status: third-party adapter — **in progress**.
Last verified: <fill in a real date when you actually check these against the provider's
published documentation>

## Upstream sources
- <url to the generation reference>
- <url to the model-listing reference>
- <url to versioning or changelog>

## Wire contract
### Endpoints
- `POST <url>` — generation
- `GET <url>` — discovery
### Auth
- <header name and value shape>
### Version pins
- <version header or path segment sent, and what omitting it does>
### Request fields
- <every field the adapter sends, and what normalized concept each carries>
### Response fields
- <every field the adapter reads, including usage and finish reasons>
### Streaming
- <framing, event shapes, termination, where usage arrives>
### Errors
- <status codes, error body shape, retry headers honored>

## Watchlist
- <what is most likely to change upstream>
"""

_README = """# {package}

The `{provider_id}` provider for [AnyInfer](https://anyinfer.dev/).

```bash
pip install {package}
```

Once installed, `{provider_id}:<model>` targets resolve through AnyInfer's registry — no
application code changes.

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("{provider_id}", api_key="env://{provider_id_upper}_API_KEY")])
print(client.generate("hello", target="{provider_id}:some-model").text)
```

## Status

Implement `adapter.py`, then certify:

```bash
anyinfer conform {provider_id} --model some-model
```

The suite reports exactly what this adapter supports. Cases this provider genuinely cannot
support are declared in `pyproject.toml` under `[tool.anyinfer.conformance]`, where they
show as ➖ rather than as failures.
"""

SCAFFOLD_FILES: dict[str, str] = {
    "{package}/__init__.py": _INIT,
    "{package}/adapter.py": _ADAPTER,
    "tests/test_conformance.py": _TEST,
    "contracts/{provider_id}.md": _CONTRACT,
    "pyproject.toml": _PYPROJECT,
    "README.md": _README,
}
"""Files the scaffold writes, keyed by path template."""
