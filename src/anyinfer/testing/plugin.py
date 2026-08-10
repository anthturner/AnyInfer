"""A pytest plugin for testing applications built on AnyInfer.

Registered through the ``pytest11`` entry point, so installing ``anyinfer`` is enough to
make the fixtures available. Nothing here runs — or imports anything expensive — unless a
test asks for a fixture.

The fixtures give each test its own provider registry. That is the load-bearing detail: a
process-wide registry shared between tests turns a provider id into a global, and two tests
that both register ``"scripted"`` then depend on execution order.

```python
def test_falls_back(anyinfer_client, anyinfer_scripted, anyinfer_events):
    provider = anyinfer_scripted(models=[ScriptedModel("m", failures=(ScriptedFailure(),))])
    result = anyinfer_client(provider).generate("hi", target=provider.target("m"))
    assert [a.outcome for a in result.attempts] == ["retried", "ok"]
```
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:  # pragma: no cover — import-time cost is the whole point of deferring
    from .. import AsyncClient, Client
    from ..events.telemetry import TelemetryEvent
    from ..manifest import RunManifest
    from ..registry import ProviderRegistry
    from .cassettes import Cassette
    from .scripted import ScriptedModel, ScriptedProvider

__all__ = [
    "RECORD_ENV_VAR",
    "EventCollector",
    "anyinfer_async_client",
    "anyinfer_cassette",
    "anyinfer_client",
    "anyinfer_events",
    "anyinfer_golden_manifest",
    "anyinfer_recording",
    "anyinfer_registry",
    "anyinfer_scripted",
    "pytest_addoption",
]

RECORD_ENV_VAR = "ANYINFER_RECORD_CASSETTES"
"""Set to ``1`` to record cassettes instead of replaying them."""


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--update-manifests``.

    Args:
        parser: The pytest command-line parser.
    """
    parser.addoption(
        "--update-manifests",
        action="store_true",
        default=False,
        help="rewrite golden run manifests instead of asserting against them",
    )


class EventCollector:
    """Collects telemetry events for assertions.

    A collector, not an assertion library: it hands back what happened and leaves the
    judging to the test. Registered payload-free unless a test explicitly opts in, so a
    suite cannot start capturing prompt text by accident.
    """

    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def on_event(self, event: TelemetryEvent) -> None:
        """Record one event."""
        self.events.append(event)

    def of_type(self, *types: type) -> list[Any]:
        """Every recorded event that is an instance of any of ``types``."""
        return [e for e in self.events if isinstance(e, types)]

    def request_ids(self) -> list[str]:
        """Correlation ids seen, in first-seen order."""
        seen: list[str] = []
        for event in self.events:
            request_id = getattr(event, "request_id", None)
            if isinstance(request_id, str) and request_id not in seen:
                seen.append(request_id)
        return seen

    def clear(self) -> None:
        """Forget everything recorded so far."""
        self.events.clear()


@pytest.fixture
def anyinfer_registry() -> ProviderRegistry:
    """A provider registry scoped to one test.

    Built-ins are loaded; entry-point discovery is off, so a third-party provider installed
    in the developer's environment cannot change how a test behaves.
    """
    from ..registry import ProviderRegistry

    return ProviderRegistry(load_builtins=True, load_entry_points=False)


@pytest.fixture
def anyinfer_scripted(
    anyinfer_registry: ProviderRegistry,
) -> Iterator[Callable[..., ScriptedProvider]]:
    """Factory for scripted providers, registered into this test's registry.

    Call it with ``models=[...]`` and, optionally, ``provider_id=``. Every provider it
    builds is reset when the test ends.
    """
    from .scripted import ScriptedProvider

    built: list[ScriptedProvider] = []

    def factory(
        models: Sequence[ScriptedModel] | None = None,
        *,
        provider_id: str = "scripted",
        **kwargs: Any,
    ) -> ScriptedProvider:
        provider = ScriptedProvider(provider_id, models, **kwargs)
        provider.register(anyinfer_registry)
        built.append(provider)
        return provider

    yield factory

    for provider in built:
        provider.reset()


@pytest.fixture
def anyinfer_events() -> EventCollector:
    """A payload-free telemetry collector."""
    return EventCollector()


@pytest.fixture
def anyinfer_async_client(
    anyinfer_registry: ProviderRegistry,
    anyinfer_events: EventCollector,
) -> Iterator[Callable[..., AsyncClient]]:
    """Factory for async clients wired to scripted providers.

    Pass the providers to serve; every client built is closed when the test ends.
    """
    from .. import AsyncClient

    built: list[AsyncClient] = []

    def factory(*providers: ScriptedProvider, **kwargs: Any) -> AsyncClient:
        client = AsyncClient(
            [p.settings() for p in providers],
            registry=anyinfer_registry,
            observers=[anyinfer_events],
            use_default_catalog=kwargs.pop("use_default_catalog", False),
            **kwargs,
        )
        built.append(client)
        return client

    yield factory

    for client in built:
        _run_sync(client.aclose())


@pytest.fixture
def anyinfer_client(
    anyinfer_registry: ProviderRegistry,
    anyinfer_events: EventCollector,
) -> Iterator[Callable[..., Client]]:
    """Factory for sync clients wired to scripted providers."""
    from .. import Client

    built: list[Client] = []

    def factory(*providers: ScriptedProvider, **kwargs: Any) -> Client:
        client = Client(
            [p.settings() for p in providers],
            registry=anyinfer_registry,
            observers=[anyinfer_events],
            use_default_catalog=kwargs.pop("use_default_catalog", False),
            **kwargs,
        )
        built.append(client)
        return client

    yield factory

    for client in built:
        client.close()


@pytest.fixture
def anyinfer_cassette(request: pytest.FixtureRequest) -> Callable[[str], Cassette]:
    """Resolve a cassette stored beside the test file.

    Replays by default; records when ``ANYINFER_RECORD_CASSETTES=1``. Recorded bodies pass
    through the redaction registry before reaching disk, so a cassette committed alongside
    a test cannot carry a registered secret.
    """
    from .cassettes import Cassette

    directory = Path(str(request.path)).parent / "cassettes"

    def resolve(name: str) -> Cassette:
        return Cassette(directory / f"{name}.json")

    return resolve


@pytest.fixture
def anyinfer_golden_manifest(
    request: pytest.FixtureRequest,
) -> Callable[[RunManifest | Any, str], None]:
    """Assert a run manifest against a golden file stored beside the test.

    Call it with the manifest and a name; the golden lands in ``manifests/<name>.json``
    next to the test file. A missing golden is written on the first run, and
    ``--update-manifests`` rewrites every one of them.

    Args:
        request: Supplied by pytest; identifies the test file the goldens sit beside.

    Returns:
        The assertion callable.
    """
    from .manifests import assert_manifest_matches

    directory = Path(str(request.path)).parent / "manifests"
    update = bool(request.config.getoption("--update-manifests"))

    def check(manifest: RunManifest | Any, name: str) -> None:
        assert manifest is not None, (
            "this generation carries no manifest; build the client with manifests=True"
        )
        assert_manifest_matches(manifest, directory / f"{name}.json", update=update)

    return check


@pytest.fixture
def anyinfer_recording() -> bool:
    """Whether cassettes are being recorded on this run."""
    return os.environ.get(RECORD_ENV_VAR, "") == "1"


_PENDING_TEARDOWNS: set[Any] = set()
"""Strong references to teardown tasks, so the loop cannot collect one mid-close."""


def _run_sync(awaitable: Any) -> None:
    """Await one coroutine from fixture teardown, whatever loop state we are in."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(awaitable)
        return
    # Teardown inside a running loop cannot block, so the close is scheduled — and held,
    # because a task with no live reference may be garbage-collected before it runs.
    task = loop.create_task(awaitable)
    _PENDING_TEARDOWNS.add(task)
    task.add_done_callback(_PENDING_TEARDOWNS.discard)
