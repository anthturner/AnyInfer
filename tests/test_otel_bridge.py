"""The OTel bridge maps every event in the contract (ADR-006).

The bridge is a *consumer* of the event contract, so it may present events differently
(span events vs. standalone spans), but it must not silently drop them. `OTelObserver`
dispatches by method name lookup, which fails open: an unmapped event type is discarded
with no error. The completeness test below is what keeps that from happening quietly when
a new event type is added.

Most tests drive a fake tracer, which keeps them fast and lets them assert on calls the
SDK would swallow (a double `end()`, for one). The final section runs the same bridge
against the real SDK and an in-memory exporter, so the attribute shapes are known to
survive export rather than only to satisfy the fake.
"""

from __future__ import annotations

import logging
from typing import Any, get_args

import pytest

import anyinfer as ai
from anyinfer.events.telemetry import TelemetryEvent
from anyinfer.otel import OTelObserver
from anyinfer.types.results import ErrorInfo, Timing, Usage


class FakeSpan:
    """Records what the bridge does to it."""

    def __init__(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.name = name
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.status: Any = None
        self.ended = False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append((name, dict(attributes or {})))

    def set_status(self, status: Any) -> None:
        self.status = status

    def end(self) -> None:
        assert not self.ended, f"span {self.name!r} ended twice"
        self.ended = True


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> FakeSpan:
        span = FakeSpan(name, attributes)
        self.spans.append(span)
        return span


class FakeInstrument:
    def __init__(self) -> None:
        self.records: list[tuple[float, dict[str, Any]]] = []

    def add(self, value: float, labels: dict[str, Any] | None = None) -> None:
        self.records.append((value, dict(labels or {})))

    def record(self, value: float, labels: dict[str, Any] | None = None) -> None:
        self.records.append((value, dict(labels or {})))


class FakeMeter:
    def create_counter(self, *args: Any, **kwargs: Any) -> FakeInstrument:
        return FakeInstrument()

    def create_histogram(self, *args: Any, **kwargs: Any) -> FakeInstrument:
        return FakeInstrument()


@pytest.fixture
def tracer() -> FakeTracer:
    return FakeTracer()


@pytest.fixture
def observer(tracer: FakeTracer) -> OTelObserver:
    pytest.importorskip("opentelemetry", reason="the bridge needs the [otel] extra")
    return OTelObserver(tracer=tracer, meter=FakeMeter())


TARGET = ai.ResolvedTarget("openai", "gpt-5")

ERROR = ErrorInfo(
    type_name="ProviderUnavailableError",
    provider="openai",
    phase="request",
    retryable=True,
    http_status=503,
    detail="upstream is down",
)

DIAGNOSTIC = ai.Diagnostic(
    code="ollama.gpu-spill",
    severity="warning",
    message="qwen3:8b is only 45% resident in VRAM",
)

# One instance of every member of the TelemetryEvent union.
ALL_EVENTS: tuple[TelemetryEvent, ...] = (
    ai.RequestStarted("r1", ("openai:gpt-5",)),
    ai.ArenaCompleted("arena-1", 3, "consensus", 2, 3, 0, False),
    ai.TargetResolved("r1", TARGET),
    ai.AttemptStarted("r1", TARGET, 1),
    ai.FirstToken("r1", TARGET, 12.5),
    ai.AttemptCompleted(
        "r1",
        TARGET,
        Usage(input_tokens=10, output_tokens=5),
        Timing(started_at=0.0, total_ms=100.0),
        "stop",
    ),
    ai.RetryScheduled("r1", TARGET, 1, 0.5, ERROR),
    ai.FallbackTriggered("r1", TARGET, "anthropic:claude-opus-5", ERROR),
    ai.RepairAttempted("r1", TARGET, 1, "json_schema", ("missing 'n'",)),
    ai.RequestCompleted(
        "r1",
        TARGET,
        Usage(input_tokens=10, output_tokens=5),
        Timing(started_at=0.0, total_ms=100.0),
    ),
    ai.RequestFailed("r1", ERROR),
    ai.ParameterDropped("r1", TARGET, "temperature", "target ignores sampling"),
    ai.UsageEstimated("r1", TARGET, "input_tokens", "heuristic"),
    ai.ProviderDiagnostic(TARGET, DIAGNOSTIC, "r1"),
    ai.ContextReduced("auto", "select", 10, 4, 6, 900, 1000, ("max_tokens",), 0),
    ai.CachePlanned("r1", TARGET, "explicit", 2, 4096),
    ai.RateLimitWaited("r1", "openai", 1.5, "provider-headers", TARGET),
    ai.RateLimitObserved("openai", requests_remaining=3, resets_in_s=12.0),
    ai.ServerLifecycle("llama-1", "ready"),
    ai.DownloadProgress("artifact-1", 1024, 1024, done=True),
    ai.CredentialRotated("openai", "auth-failure"),
    ai.BatchSubmitted("msgbatch_1", TARGET, 500),
    ai.BatchCompleted("msgbatch_1", TARGET, "completed", 498, 2),
)


def test_every_event_type_has_a_handler() -> None:
    """The union and the bridge must not drift apart.

    Adding an event type without a `_on_<Name>` method makes the bridge lossy, and the
    name-based dispatch gives no error when it happens.
    """
    unmapped = [
        event_type.__name__
        for event_type in get_args(TelemetryEvent)
        if not hasattr(OTelObserver, f"_on_{event_type.__name__}")
    ]
    assert not unmapped, f"event types with no OTel mapping: {unmapped}"


def test_the_sample_set_covers_the_whole_union() -> None:
    """Guards the test below: an uncovered type would silently pass it."""
    covered = {type(e) for e in ALL_EVENTS}
    assert covered == set(get_args(TelemetryEvent))


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda e: type(e).__name__)
def test_every_event_produces_otel_output(
    observer: OTelObserver, tracer: FakeTracer, event: TelemetryEvent
) -> None:
    """Every event visibly changes the trace: a new span, or an event on the open one.

    Delivered against an already-open request span, so request-scoped events have a
    parent to attach to. `RequestStarted` opens a second span, which still counts as a
    new span.
    """
    request_span = _started(observer, tracer)
    spans_before = len(tracer.spans)
    events_before = len(request_span.events)
    attributes_before = dict(request_span.attributes)

    observer.on_event(event)

    produced = (
        len(tracer.spans) > spans_before  # a standalone span
        or len(request_span.events) > events_before  # a span event
        or request_span.attributes != attributes_before  # enriched the request span
        or request_span.ended  # terminated the request
    )
    assert produced, f"{type(event).__name__} produced no OTel output — the bridge dropped it"


# ---- request-scoped events -----------------------------------------------------------


def _started(observer: OTelObserver, tracer: FakeTracer) -> FakeSpan:
    observer.on_event(ai.RequestStarted("r1", ("openai:gpt-5",)))
    return tracer.spans[0]


def test_target_resolved_records_the_concrete_target(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    span = _started(observer, tracer)
    observer.on_event(ai.TargetResolved("r1", TARGET))

    name, attributes = span.events[-1]
    assert name == "target.resolved"
    assert attributes["gen_ai.system"] == "openai"
    assert attributes["gen_ai.request.model"] == "gpt-5"


def test_fallback_names_both_targets_and_the_cause(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    span = _started(observer, tracer)
    observer.on_event(ai.FallbackTriggered("r1", TARGET, "anthropic:claude-opus-5", ERROR))

    name, attributes = span.events[-1]
    assert name == "fallback.triggered"
    assert attributes["gen_ai.anyinfer.from_target"] == "openai:gpt-5"
    assert attributes["gen_ai.anyinfer.to_target"] == "anthropic:claude-opus-5"
    assert attributes["gen_ai.anyinfer.error_type"] == "ProviderUnavailableError"


def test_fallback_without_an_error_omits_the_error_attribute(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """A fallback can be triggered by health or policy rather than a failure."""
    span = _started(observer, tracer)
    observer.on_event(ai.FallbackTriggered("r1", TARGET, "anthropic:claude-opus-5"))

    _, attributes = span.events[-1]
    assert "gen_ai.anyinfer.error_type" not in attributes


def test_usage_estimated_marks_the_derived_field(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """Estimated and reported numbers must stay distinguishable in a trace."""
    span = _started(observer, tracer)
    observer.on_event(ai.UsageEstimated("r1", TARGET, "input_tokens", "heuristic"))

    name, attributes = span.events[-1]
    assert name == "usage.estimated"
    assert attributes["gen_ai.anyinfer.field"] == "input_tokens"
    assert attributes["gen_ai.anyinfer.method"] == "heuristic"


def test_request_scoped_events_without_a_span_are_dropped_quietly(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """Events for an unknown request must not raise or fabricate a span."""
    observer.on_event(ai.TargetResolved("never-started", TARGET))
    observer.on_event(ai.FallbackTriggered("never-started", TARGET, "x:y"))
    observer.on_event(ai.UsageEstimated("never-started", TARGET, "input_tokens", "h"))

    assert tracer.spans == []


# ---- events outside a request scope ---------------------------------------------------


def test_context_reduced_becomes_a_standalone_span(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(ai.ContextReduced("auto", "select", 10, 4, 6, 900, 1000, ("max_tokens",), 0))

    span = tracer.spans[0]
    assert span.name == "context.reduced"
    assert span.ended
    assert span.attributes["gen_ai.anyinfer.representation"] == "select"
    assert span.attributes["gen_ai.anyinfer.omitted_count"] == 6
    assert span.attributes["gen_ai.anyinfer.binding_constraints"] == ["max_tokens"]


def test_context_reduced_span_carries_no_document_content(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """`ContextReduced` is content-free by construction; the bridge must not change that."""
    observer.on_event(ai.ContextReduced("auto", "select", 10, 4, 6, 900, 1000))

    for value in tracer.spans[0].attributes.values():
        assert not isinstance(value, str) or "/" not in value


def test_a_diagnostic_in_a_request_lands_on_that_request_span(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(ai.RequestStarted("r1", ("openai:gpt-5",)))
    spans_before = len(tracer.spans)
    observer.on_event(ai.ProviderDiagnostic(TARGET, DIAGNOSTIC, "r1"))

    assert len(tracer.spans) == spans_before, "no standalone span while a request owns it"
    name, attributes = tracer.spans[0].events[-1]
    assert name == "provider.diagnostic"
    assert attributes["gen_ai.anyinfer.code"] == "ollama.gpu-spill"
    assert attributes["gen_ai.anyinfer.severity"] == "warning"


def test_a_diagnostic_outside_a_request_becomes_a_standalone_span(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(ai.ProviderDiagnostic(TARGET, DIAGNOSTIC))

    span = tracer.spans[0]
    assert span.name == "provider.diagnostic"
    assert span.ended
    assert span.attributes["gen_ai.system"] == "openai"
    assert span.attributes["gen_ai.anyinfer.code"] == "ollama.gpu-spill"


def test_server_lifecycle_becomes_a_standalone_span(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(ai.ServerLifecycle("llama-1", "ready"))

    span = tracer.spans[0]
    assert span.name == "server.lifecycle"
    assert span.attributes["gen_ai.anyinfer.state"] == "ready"
    assert span.status is None
    assert span.ended


def test_a_crashed_server_sets_an_error_status(observer: OTelObserver, tracer: FakeTracer) -> None:
    observer.on_event(ai.ServerLifecycle("llama-1", "crashed", "exit code 1"))

    span = tracer.spans[0]
    assert span.status is not None, "a crash must not read as a healthy span"
    assert span.attributes["gen_ai.anyinfer.detail"] == "exit code 1"
    assert span.ended


def test_download_progress_spans_only_on_completion(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """Per-chunk progress would flood the exporter; only the terminal event is a span."""
    observer.on_event(ai.DownloadProgress("artifact-1", 512, 1024))
    assert tracer.spans == []

    observer.on_event(ai.DownloadProgress("artifact-1", 1024, 1024, done=True))
    span = tracer.spans[0]
    assert span.name == "download.completed"
    assert span.attributes["gen_ai.anyinfer.total_bytes"] == 1024
    assert span.ended


def test_download_of_unknown_size_omits_the_total(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(ai.DownloadProgress("artifact-1", 1024, None, done=True))

    assert "gen_ai.anyinfer.total_bytes" not in tracer.spans[0].attributes


def test_standalone_spans_do_not_disturb_an_in_flight_request(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """A download finishing mid-request must not end or pollute the request span."""
    request_span = _started(observer, tracer)
    observer.on_event(ai.DownloadProgress("artifact-1", 1024, 1024, done=True))
    observer.on_event(ai.ServerLifecycle("llama-1", "ready"))

    assert not request_span.ended
    assert request_span.events == []


# ---- against the real SDK -------------------------------------------------------------
#
# The fake accepts any Python object as an attribute value; the SDK does not. It drops
# invalid types with a warning, so a span can export with attributes silently missing —
# a failure mode no fake-tracer assertion can reach.


@pytest.fixture
def exporter() -> Any:
    # Every SDK submodule goes through importorskip: the SDK is a dev-only dependency, so a
    # contributor without it must see skips, not errors.
    reason = "real-export checks need opentelemetry-sdk"
    sdk = pytest.importorskip("opentelemetry.sdk.trace", reason=reason)
    export = pytest.importorskip("opentelemetry.sdk.trace.export", reason=reason)
    in_memory = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter", reason=reason
    )

    memory = in_memory.InMemorySpanExporter()
    provider = sdk.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(memory))
    memory.tracer = provider.get_tracer("test")
    return memory


@pytest.fixture
def sdk_observer(exporter: Any) -> OTelObserver:
    return OTelObserver(tracer=exporter.tracer, meter=FakeMeter())


def test_every_event_exports_cleanly_through_the_sdk(
    sdk_observer: OTelObserver, exporter: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole event set survives real export with no attribute rejected.

    The SDK drops any attribute whose value is not a bool, str, bytes, int, float, or a
    homogeneous sequence of those — it *logs* the rejection rather than raising or warning,
    so a Decimal or a dict would vanish from the trace while every assertion still passed.
    Checking the log is the only way to see it.
    """
    with caplog.at_level(logging.WARNING, logger="opentelemetry"):
        for event in ALL_EVENTS:
            sdk_observer.on_event(event)

    rejected = [r.getMessage() for r in caplog.records if "Invalid type" in r.getMessage()]
    assert not rejected, f"the SDK dropped attributes: {rejected}"
    assert exporter.get_finished_spans(), "nothing exported"


def test_a_request_exports_as_one_span_with_attempts_as_events(
    sdk_observer: OTelObserver, exporter: Any
) -> None:
    """The fallback chain reads as a single trace, not several disconnected ones."""
    sdk_observer.on_event(ai.RequestStarted("r1", ("openai:gpt-5", "anthropic:claude-opus-5")))
    sdk_observer.on_event(ai.TargetResolved("r1", TARGET))
    sdk_observer.on_event(ai.AttemptStarted("r1", TARGET, 1))
    sdk_observer.on_event(ai.FallbackTriggered("r1", TARGET, "anthropic:claude-opus-5", ERROR))
    sdk_observer.on_event(ai.UsageEstimated("r1", TARGET, "input_tokens", "heuristic"))
    sdk_observer.on_event(
        ai.RequestCompleted("r1", TARGET, Usage(), Timing(started_at=0.0, total_ms=100.0))
    )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1, "one request must export as exactly one span"
    span = spans[0]
    assert span.name == "generate"
    assert [e.name for e in span.events] == [
        "target.resolved",
        "attempt.started",
        "fallback.triggered",
        "usage.estimated",
    ]


def test_context_reduced_tuple_attribute_survives_export(
    sdk_observer: OTelObserver, exporter: Any
) -> None:
    """`binding_constraints` is a tuple; the SDK accepts only a list-like of scalars."""
    sdk_observer.on_event(
        ai.ContextReduced("auto", "select", 10, 4, 6, 900, 1000, ("max_tokens", "per_doc"), 0)
    )

    span = exporter.get_finished_spans()[0]
    assert span.name == "context.reduced"
    assert span.attributes["gen_ai.anyinfer.binding_constraints"] == ("max_tokens", "per_doc")


def test_a_crashed_server_exports_an_error_status(
    sdk_observer: OTelObserver, exporter: Any
) -> None:
    from opentelemetry.trace import StatusCode

    sdk_observer.on_event(ai.ServerLifecycle("llama-1", "crashed", "exit code 1"))

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR


def test_a_failed_request_exports_an_error_status(
    sdk_observer: OTelObserver, exporter: Any
) -> None:
    from opentelemetry.trace import StatusCode

    sdk_observer.on_event(ai.RequestStarted("r1", ("openai:gpt-5",)))
    sdk_observer.on_event(ai.RequestFailed("r1", ERROR))

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["error.type"] == "ProviderUnavailableError"


# ---- operation-tagged spans (embedding and rerank) ----------------------------------


def test_embedding_request_produces_an_embeddings_span(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(
        ai.RequestStarted("e1", ("cohere:embed-v4.0",), operation="embedding")
    )

    span = tracer.spans[-1]
    assert span.name == "embeddings"
    assert span.attributes["gen_ai.operation.name"] == "embeddings"
    assert "gen_ai.prompt" not in span.attributes


def test_rerank_request_produces_a_rerank_span(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    observer.on_event(ai.RequestStarted("rr1", ("cohere:rerank-v3.5",), operation="rerank"))

    span = tracer.spans[-1]
    assert span.name == "rerank"
    assert span.attributes["gen_ai.operation.name"] == "rerank"


def test_generation_span_shape_is_unchanged_by_operation_tagging(
    observer: OTelObserver, tracer: FakeTracer
) -> None:
    """An untagged RequestStarted must produce exactly the pre-tagging span."""
    observer.on_event(ai.RequestStarted("g1", ("openai:gpt-5",)))

    span = tracer.spans[-1]
    assert span.name == "generate"
    assert span.attributes["gen_ai.operation.name"] == "chat"
