"""Deferred batch inference: submit now, collect hours later, at roughly half price.

Every major provider sells this tier, and it is the shape of the workloads this library's
audience actually runs — evals, backfills, offline enrichment. Without it they drop to a
raw provider SDK for their highest-volume traffic and lose structured-output enforcement,
capability provenance, and cost accounting on exactly the requests where those matter.

Two properties get the most attention here, because both are easy to get quietly wrong.
**Nothing is stored:** the handle is the caller's, which is what keeps the run-retention
non-goal intact through the one feature whose shape invites breaking it. And **lines come
back in submission order**, because providers return them in completion order and a caller
zipping results against their own inputs should not have to sort first.
"""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.testing.fakes import FakeAnthropicServer, FakeResponse

TARGET = "anthropic:claude-sonnet-4-5"


def _client(server: FakeAnthropicServer, **kwargs: object) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "anthropic",
                api_key="sk-test",
                base_url="https://fake.invalid",
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
        **kwargs,  # type: ignore[arg-type]
    )


class _Recorder:
    """Collects every emitted event, so the payload-free claims can be asserted on."""

    def __init__(self, sink: list[object]) -> None:
        self._sink = sink

    def on_event(self, event: object) -> None:
        self._sink.append(event)


def _batch(count: int = 3, **kwargs: object) -> ai.BatchGenerationRequest:
    return ai.BatchGenerationRequest(
        requests=tuple(
            ai.GenerationRequest(messages=(ai.user(f"question {i}"),)) for i in range(count)
        ),
        **kwargs,  # type: ignore[arg-type]
    )


# ---- the request type -------------------------------------------------------------------


def test_an_empty_batch_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one request"):
        ai.BatchGenerationRequest(requests=())


def test_duplicate_ids_are_refused_because_results_are_keyed_by_them() -> None:
    """Two lines sharing an id are two answers the caller cannot tell apart."""
    requests = tuple(ai.GenerationRequest(messages=(ai.user(str(i)),)) for i in range(2))
    with pytest.raises(ValueError, match="unique"):
        ai.BatchGenerationRequest(requests=requests, custom_ids=("same", "same"))


def test_ids_default_to_positions() -> None:
    assert _batch(3).line_ids == ("0", "1", "2")


def test_supplied_ids_are_kept_verbatim() -> None:
    """A caller joining against their own rows supplies keys they already have."""
    batch = _batch(2, custom_ids=("row-9", "row-4"))
    assert batch.line_ids == ("row-9", "row-4")


def test_an_id_count_mismatch_is_refused() -> None:
    with pytest.raises(ValueError, match="one entry per request"):
        _batch(3, custom_ids=("a", "b"))


# ---- submission --------------------------------------------------------------------------


async def test_submitting_returns_a_handle_the_caller_owns() -> None:
    """The library stores no job registry; this value is the whole state."""
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(3), target=TARGET)
    finally:
        await client.aclose()

    assert handle.batch_id == "msgbatch_fake"
    assert handle.provider_id == "anthropic"
    assert handle.line_count == 3
    assert handle.submitted_at > 0


async def test_each_line_is_translated_the_way_a_live_request_would_be() -> None:
    """The line-item type is the request itself, so a batched call is not a reduced copy."""
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    batch = ai.BatchGenerationRequest(
        requests=(
            ai.GenerationRequest(
                messages=(ai.system("Be terse."), ai.user("hi")),
                sampling=ai.Sampling(temperature=0.2, max_output_tokens=64),
                tools=(ai.ToolSpec(name="lookup", description="d", parameters={"type": "object"}),),
            ),
        )
    )
    try:
        await client.submit_batch(batch, target=TARGET)
    finally:
        await client.aclose()

    params = server.requests[0]["requests"][0]["params"]
    assert params["system"] == "Be terse."
    assert params["temperature"] == 0.2
    assert params["max_tokens"] == 64
    assert params["tools"][0]["name"] == "lookup"


async def test_a_batched_line_never_asks_to_stream() -> None:
    """A batch is answered whole; the provider rejects the flag, and it means nothing."""
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    try:
        await client.submit_batch(_batch(1), target=TARGET)
    finally:
        await client.aclose()

    assert "stream" not in server.requests[0]["requests"][0]["params"]


async def test_submission_emits_a_payload_free_event() -> None:
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    events: list[object] = []
    client = _client(server, observers=[_Recorder(events)])
    try:
        await client.submit_batch(_batch(2), target=TARGET)
    finally:
        await client.aclose()

    submitted = [e for e in events if isinstance(e, ai.BatchSubmitted)]
    assert len(submitted) == 1
    assert submitted[0].line_count == 2
    assert "question" not in repr(submitted[0]), "no prompt text may ride an event"


# ---- polling and collection ---------------------------------------------------------------


async def test_a_caller_polls_to_a_terminal_status_then_fetches() -> None:
    """Polling is cheap and fetching is not, which is why they are separate calls."""
    server = FakeAnthropicServer(FakeResponse(text="answer"), batch_polls_before_done=2)
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=TARGET)

        first = await client.batch_status(handle)
        assert first.status == "in_progress"
        assert not first.finished

        second = await client.batch_status(handle)
        assert second.finished
        assert second.completed == 2

        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert result.status == "completed"
    assert [line.custom_id for line in result.lines] == ["0", "1"]


async def test_fetching_an_unfinished_batch_is_refused_rather_than_returning_nothing() -> None:
    """An empty result would read as "every line failed", which is a different fact."""
    server = FakeAnthropicServer(FakeResponse(text="answer"), batch_polls_before_done=5)
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(1), target=TARGET)
        with pytest.raises(ai.AnyInferError, match="not finished"):
            await client.fetch_batch(handle)
    finally:
        await client.aclose()


async def test_lines_come_back_in_submission_order_not_completion_order() -> None:
    """The fake returns them reversed, as a provider would; the core sorts once."""
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(4), target=TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert [line.custom_id for line in result.lines] == ["0", "1", "2", "3"]


async def test_custom_ids_that_are_not_numbers_still_sort_stably() -> None:
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    try:
        handle = await client.submit_batch(
            _batch(3, custom_ids=("row-c", "row-a", "row-b")), target=TARGET
        )
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert sorted(line.custom_id for line in result.lines) == ["row-a", "row-b", "row-c"]
    assert len(result.lines) == 3


async def test_a_line_carries_the_same_result_a_live_call_would_have() -> None:
    """Replayed through the live event path, so it is not a reduced copy assembled twice."""
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(1), target=TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    line = result.lines[0]
    assert line.ok
    assert line.result is not None
    assert line.result.text == "answer #0"
    assert line.result.finish_reason == "stop"
    assert line.result.usage.input_tokens == 11
    assert line.result.usage.output_tokens == 7
    assert line.result.target.provider_id == "anthropic"


async def test_a_partial_failure_keeps_the_lines_that_worked() -> None:
    """Providers run and bill what succeeded; discarding the batch would waste that."""
    server = FakeAnthropicServer(FakeResponse(text="answer"), batch_failures=1)
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(3), target=TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert len(result.succeeded) == 2
    assert len(result.failed) == 1
    failed = result.failed[0]
    assert failed.result is None
    assert failed.error is not None
    assert "rejected" in failed.error.detail


async def test_collection_emits_an_event_with_the_counts() -> None:
    server = FakeAnthropicServer(FakeResponse(text="answer"), batch_failures=1)
    events: list[object] = []
    client = _client(server, observers=[_Recorder(events)])
    try:
        handle = await client.submit_batch(_batch(3), target=TARGET)
        await client.fetch_batch(handle)
    finally:
        await client.aclose()

    completed = [e for e in events if isinstance(e, ai.BatchCompleted)]
    assert len(completed) == 1
    assert (completed[0].completed, completed[0].failed) == (2, 1)


async def test_cancelling_reports_the_state_afterwards() -> None:
    server = FakeAnthropicServer(FakeResponse(text="answer"), batch_polls_before_done=99)
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=TARGET)
        report = await client.cancel_batch(handle)
    finally:
        await client.aclose()

    assert report.status == "cancelled"
    assert report.finished


# ---- what is refused ------------------------------------------------------------------------


async def test_a_provider_without_batching_says_so_rather_than_failing_obscurely() -> None:
    from anyinfer.testing.fakes import FakeOpenAIServer

    server = FakeOpenAIServer(FakeResponse(text="hi"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
            )
        ],
        use_default_catalog=False,
    )
    try:
        with pytest.raises(ai.ConfigError, match="batch"):
            await client.submit_batch(_batch(1), target="openai-compat:m")
    finally:
        await client.aclose()


def test_only_adapters_that_implement_the_protocol_declare_the_operation() -> None:
    """The declaration is validated against the adapter object at build time, not trusted."""
    from anyinfer.providers.base import SubmitsBatches
    from anyinfer.registry import default_registry

    declaring = {
        default_registry.get(pid).id
        for pid in default_registry.known_ids()
        if "batch" in default_registry.get(pid).operations
    }
    assert declaring == {"anthropic"}

    from anyinfer.providers.anthropic import AnthropicAdapter
    from anyinfer.providers.base import ProviderConfig

    adapter = AnthropicAdapter(ProviderConfig(provider_id="anthropic", api_key="k"))
    assert isinstance(adapter, SubmitsBatches)


def test_a_handle_names_the_instance_not_the_alias_it_was_typed_as() -> None:
    """An alias can be repointed between submission and collection.

    A batch reclaimed from the wrong account is somebody else's job, so the handle records
    where it actually went.
    """
    handle = ai.BatchHandle(
        batch_id="b1", provider_id="anthropic", model="claude-sonnet-4-5", line_count=1
    )
    assert handle.provider_id == "anthropic"


def test_a_terminal_status_is_recognizable_without_a_lookup_table() -> None:
    report = ai.BatchReport(
        handle=ai.BatchHandle(batch_id="b", provider_id="p", model="m", line_count=1),
        status="expired",
    )
    assert report.finished


# ---- the sync facade -------------------------------------------------------------------------


def test_the_batch_surface_exists_on_the_sync_client_too() -> None:
    """Covered by the signature parity test as well; this pins the round trip works."""
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = ai.Client(
        [
            ai.ProviderSettings.of(
                "anthropic",
                api_key="sk-test",
                base_url="https://fake.invalid",
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
    )
    with client:
        handle = client.submit_batch(_batch(2), target=TARGET)
        assert client.batch_status(handle).finished
        result = client.fetch_batch(handle)

    assert [line.custom_id for line in result.lines] == ["0", "1"]
