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

import json

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


async def test_caller_supplied_ids_come_back_in_submission_order_not_alphabetical() -> None:
    """Sorting cannot substitute for remembering, and getting this wrong is silent.

    Every answer would be correct and attached to the wrong row — the caller zips
    `result.lines` against their own inputs and the pairing is off, with nothing anywhere
    to say so. Which is why the handle records the order rather than the result inferring
    it.
    """
    submitted = ("row-c", "row-a", "row-b")
    server = FakeAnthropicServer(FakeResponse(text="answer"))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(3, custom_ids=submitted), target=TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert tuple(line.custom_id for line in result.lines) == submitted
    assert tuple(line.custom_id for line in result.lines) != tuple(sorted(submitted))


def test_the_handle_records_what_was_submitted_and_in_what_order() -> None:
    """The one piece of state that cannot be recovered from the provider."""
    from anyinfer._client.async_client import _ordered_lines
    from anyinfer.types.operations import BatchLine as Line

    handle = ai.BatchHandle(
        batch_id="b", provider_id="p", model="m", line_count=3, line_ids=("c", "a", "b")
    )
    completion_order = ai.BatchResult(
        handle=handle,
        status="completed",
        lines=(Line(custom_id="a"), Line(custom_id="b"), Line(custom_id="c")),
    )
    assert tuple(line.custom_id for line in _ordered_lines(completion_order).lines) == ("c", "a", "b")


def test_an_unexpected_id_is_appended_rather_than_dropped() -> None:
    """A provider surprise is worth surfacing, not evidence the answer is worthless."""
    from anyinfer._client.async_client import _ordered_lines
    from anyinfer.types.operations import BatchLine as Line

    handle = ai.BatchHandle(
        batch_id="b", provider_id="p", model="m", line_count=1, line_ids=("a",)
    )
    result = ai.BatchResult(
        handle=handle, status="completed", lines=(Line(custom_id="?"), Line(custom_id="a"))
    )
    assert tuple(line.custom_id for line in _ordered_lines(result).lines) == ("a", "?")


# ---- what a batched line was missing --------------------------------------------------
#
# E.1 exists because callers "lose structured-output enforcement, telemetry, and cost
# accounting on their highest-volume traffic" by dropping to a raw provider SDK. A batched
# result that skipped validation and carried no cost would have given up exactly that.


async def test_a_schema_is_enforced_on_every_line() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    server = FakeAnthropicServer(FakeResponse(text='{"n": 7}'))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=TARGET)
        result = await client.fetch_batch(handle, schema=schema)
    finally:
        await client.aclose()

    assert all(line.result is not None for line in result.lines)
    assert [line.result.structured for line in result.lines if line.result] == [
        {"n": 7},
        {"n": 7},
    ]


async def test_a_violating_line_fails_alone_rather_than_discarding_the_batch() -> None:
    """The provider billed for all of them; one bad answer must not throw away the rest."""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    server = FakeAnthropicServer(FakeResponse(text="not json at all"))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=TARGET)
        result = await client.fetch_batch(handle, schema=schema)
    finally:
        await client.aclose()

    assert len(result.failed) == 2
    assert all(
        line.error is not None and line.error.type_name == "SchemaViolationError"
        for line in result.failed
    )


async def test_no_schema_means_no_validation_and_no_surprise() -> None:
    """Collection happens in another process; the schema is passed, never remembered."""
    server = FakeAnthropicServer(FakeResponse(text="free-form prose"))
    client = _client(server)
    try:
        handle = await client.submit_batch(_batch(1), target=TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert result.lines[0].ok
    assert result.lines[0].result is not None
    assert result.lines[0].result.structured is None


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
    assert "anthropic" in declaring

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


# ---- the OpenAI Batch API ----------------------------------------------------------------
#
# A three-step lifecycle where Anthropic's is one: upload a JSONL file, submit a batch
# referencing it, download the results as more files. The plan named this provider first,
# and the file dance is the reason — it is the shape the protocol has to survive, not the
# convenient one it was designed against.

from anyinfer.testing.fakes import FakeResponsesBatchServer  # noqa: E402

OPENAI_TARGET = "openai:gpt-5"


def _openai_client(server: FakeResponsesBatchServer) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai",
                api_key="sk-test",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
    )


async def test_the_job_is_uploaded_as_jsonl_before_the_batch_references_it() -> None:
    server = FakeResponsesBatchServer(FakeResponse(text="answer"))
    client = _openai_client(server)
    try:
        handle = await client.submit_batch(_batch(3), target=OPENAI_TARGET)
    finally:
        await client.aclose()

    assert handle.batch_id == "batch_fake"
    assert handle.line_count == 3

    uploaded = [json.loads(line) for line in server.uploaded[0].splitlines()]
    assert [entry["custom_id"] for entry in uploaded] == ["0", "1", "2"]
    assert all(entry["method"] == "POST" for entry in uploaded)
    # The absolute path, not the live `/responses` one: the Batch API validates this
    # field against a fixed list of full paths rather than resolving it against a base URL,
    # so the live path is rejected at submit.
    assert all(entry["url"] == "/v1/responses" for entry in uploaded)

    submitted = server.requests[0]
    assert submitted["input_file_id"] == "file-input"
    assert submitted["endpoint"] == "/v1/responses"
    assert submitted["completion_window"] == "24h"


async def test_each_uploaded_line_is_the_live_request_body() -> None:
    """Serialized by the same `build_payload`, so a batched call is not a second dialect."""
    server = FakeResponsesBatchServer(FakeResponse(text="answer"))
    client = _openai_client(server)
    batch = ai.BatchGenerationRequest(
        requests=(
            ai.GenerationRequest(
                messages=(ai.system("Be terse."), ai.user("hi")),
                sampling=ai.Sampling(temperature=0.3, max_output_tokens=32),
            ),
        )
    )
    try:
        await client.submit_batch(batch, target=OPENAI_TARGET)
    finally:
        await client.aclose()

    body = json.loads(server.uploaded[0])["body"]
    assert body["instructions"] == "Be terse."
    assert body["temperature"] == 0.3
    assert body["max_output_tokens"] == 32
    assert "stream" not in body, "a batch is answered whole; the API rejects the flag"


async def test_the_openai_lifecycle_polls_then_downloads() -> None:
    server = FakeResponsesBatchServer(FakeResponse(text="answer"), polls_before_done=2)
    client = _openai_client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=OPENAI_TARGET)

        assert (await client.batch_status(handle)).status == "in_progress"
        assert (await client.batch_status(handle)).finished

        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert result.status == "completed"
    assert [line.custom_id for line in result.lines] == ["0", "1"]
    assert result.lines[0].result is not None
    assert result.lines[0].result.text == "answer #0"
    assert result.lines[0].result.usage.total_tokens == 18


async def test_rejected_lines_are_read_from_the_error_file_too() -> None:
    """Reading only the output file would silently drop every failure.

    OpenAI splits them across two files, unlike Anthropic's single manifest — so a batch
    would come back looking smaller than it was submitted, with no error to explain it.
    """
    server = FakeResponsesBatchServer(FakeResponse(text="answer"), failures=2)
    client = _openai_client(server)
    try:
        handle = await client.submit_batch(_batch(5), target=OPENAI_TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert len(result.lines) == 5, "every submitted line is accounted for"
    assert len(result.succeeded) == 3
    assert len(result.failed) == 2
    assert all("rejected" in line.error.detail for line in result.failed if line.error)


async def test_openai_statuses_normalize_to_one_vocabulary() -> None:
    """Richer than Anthropic's two states, mapped so a caller polls one vocabulary."""
    from anyinfer.providers._openai_batch import BATCH_STATUSES

    assert BATCH_STATUSES["validating"] == "queued"
    assert BATCH_STATUSES["finalizing"] == "in_progress"
    assert BATCH_STATUSES["cancelled"] == "cancelled"
    assert BATCH_STATUSES["expired"] == "expired"


async def test_cancelling_an_openai_batch_reports_cancelled() -> None:
    server = FakeResponsesBatchServer(FakeResponse(text="answer"), polls_before_done=99)
    client = _openai_client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=OPENAI_TARGET)
        report = await client.cancel_batch(handle)
    finally:
        await client.aclose()

    assert report.status == "cancelled"
    assert report.finished


async def test_openai_lines_also_come_back_in_submission_order() -> None:
    server = FakeResponsesBatchServer(FakeResponse(text="answer"))
    client = _openai_client(server)
    try:
        handle = await client.submit_batch(_batch(4), target=OPENAI_TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert [line.custom_id for line in result.lines] == ["0", "1", "2", "3"]


def test_the_named_providers_declare_the_operation() -> None:
    """The plan named five; these are the ones whose endpoints this repo has bound."""
    from anyinfer.registry import default_registry

    declaring = {
        default_registry.get(pid).id
        for pid in default_registry.known_ids()
        if "batch" in default_registry.get(pid).operations
    }
    assert declaring == {"anthropic", "openai", "groq", "bedrock", "vertex"}


# ---- the same lifecycle on the chat dialect --------------------------------------------------
#
# The plan named five providers, not two. Groq sells the OpenAI-shaped batch tier against
# chat completions rather than Responses, which is the whole difference — so the lifecycle
# is shared code and only the line bodies differ.


async def test_a_chat_dialect_provider_runs_the_same_lifecycle() -> None:
    server = FakeResponsesBatchServer(
        FakeResponse(text="answer"), dialect="chat", polls_before_done=2
    )
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "groq",
                api_key="gsk-test",
                base_url="https://fake.invalid/openai/v1",
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
    )
    try:
        handle = await client.submit_batch(_batch(2), target="groq:llama-3.3-70b")
        assert not (await client.batch_status(handle)).finished
        assert (await client.batch_status(handle)).finished
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    uploaded = [json.loads(line) for line in server.uploaded[0].splitlines()]
    assert all(entry["url"] == "/v1/chat/completions" for entry in uploaded)
    assert server.requests[0]["endpoint"] == "/v1/chat/completions"

    assert [line.custom_id for line in result.lines] == ["0", "1"]
    assert [line.result.text for line in result.lines] == ["answer #0", "answer #1"]
    assert result.lines[0].result.usage.input_tokens == 11
    assert result.lines[0].result.finish_reason == "stop"


def test_a_preset_without_a_verified_batch_tier_does_not_claim_one() -> None:
    """Chat compatibility does not imply batch compatibility.

    Every compat preset shares the adapter that now carries the batch lifecycle, so the
    declaration is the only thing separating a provider that sells the tier from one that
    would 404 at submit.
    """
    from anyinfer.registry import default_registry

    assert "batch" in default_registry.get("groq").operations
    assert "batch" not in default_registry.get("cerebras").operations
    assert "batch" not in default_registry.get("together").operations


# ---- storage-staged batches ------------------------------------------------------------------
#
# Bedrock and Vertex do not carry a batch over the API at all: the lines are an object in
# the caller's own bucket, and the job references it by URI. That is a third lifecycle
# shape beside Anthropic's one-step and OpenAI's file dance, and it is the one that makes
# the handle carry state — the output location is not derivable from the job id, and an
# adapter that remembered it would be the job registry this design exists to avoid.

from anyinfer.testing.fakes import FakeBedrockServer  # noqa: E402

BEDROCK_TARGET = "bedrock:anthropic.claude-sonnet-4-5-v1:0"
_BEDROCK_OPTIONS = {
    "aws_access_key_id": "AKIAFAKE",
    "aws_secret_access_key": "secret",
    "region": "us-east-1",
    "batch_s3_uri": "s3://my-bucket/anyinfer",
    "batch_role_arn": "arn:aws:iam::1234:role/AnyInferBatch",
}


def _bedrock_client(server: FakeBedrockServer, **options: object) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "bedrock",
                options={**_BEDROCK_OPTIONS, **options},
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
    )


async def test_the_lines_are_staged_in_the_callers_bucket_before_the_job_is_created() -> None:
    server = FakeBedrockServer(FakeResponse(text="answer"))
    client = _bedrock_client(server)
    try:
        handle = await client.submit_batch(_batch(3), target=BEDROCK_TARGET)
    finally:
        await client.aclose()

    assert len(server.objects) == 1
    url, content = next(iter(server.objects.items()))
    assert url.startswith("https://my-bucket.s3.us-east-1.amazonaws.com/anyinfer/anyinfer-")

    staged = [json.loads(line) for line in content.decode().splitlines()]
    assert [entry["recordId"] for entry in staged] == ["0", "1", "2"]
    # The live Converse body, not a reduced copy of it.
    assert "messages" in staged[0]["modelInput"]
    assert "stream" not in staged[0]["modelInput"]

    job = server.requests[0]
    assert job["modelId"] == "anthropic.claude-sonnet-4-5-v1:0"
    assert job["roleArn"] == "arn:aws:iam::1234:role/AnyInferBatch"
    assert job["inputDataConfig"]["s3InputDataConfig"]["s3InputFormat"] == "JSONL"
    assert handle.batch_id.startswith("arn:aws:bedrock:")


async def test_the_handle_records_where_the_answers_will_land() -> None:
    """Nothing else can: the job object reports the prefix, not the file."""
    server = FakeBedrockServer(FakeResponse(text="answer"))
    client = _bedrock_client(server)
    try:
        handle = await client.submit_batch(_batch(1), target=BEDROCK_TARGET)
    finally:
        await client.aclose()

    assert handle.provider_state["output_uri"].startswith("s3://my-bucket/anyinfer/anyinfer-")
    assert handle.provider_state["output_uri"].endswith(".jsonl.out")


async def test_a_storage_staged_batch_polls_then_reads_its_answers_back() -> None:
    server = FakeBedrockServer(FakeResponse(text="answer"), batch_polls_before_done=2)
    client = _bedrock_client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=BEDROCK_TARGET)
        assert (await client.batch_status(handle)).status == "in_progress"
        assert (await client.batch_status(handle)).finished
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    # The fake answers in reverse, as a provider would; submission order is restored.
    assert [line.custom_id for line in result.lines] == ["0", "1"]
    assert [line.result.text for line in result.lines] == ["answer #0", "answer #1"]
    assert result.lines[0].result.usage.input_tokens == 11
    assert result.lines[0].result.finish_reason == "stop"


async def test_a_rejected_record_fails_alone_though_it_shares_a_file_with_the_answers() -> None:
    """Bedrock puts failures beside successes rather than in a second file."""
    server = FakeBedrockServer(FakeResponse(text="answer"), batch_failures=1)
    client = _bedrock_client(server)
    try:
        handle = await client.submit_batch(_batch(3), target=BEDROCK_TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert len(result.lines) == 3
    failed = [line for line in result.lines if line.error is not None]
    assert len(failed) == 1
    assert "record rejected" in failed[0].error.detail
    assert all(line.result is not None for line in result.lines if line.error is None)


async def test_stopping_a_job_reports_where_it_landed() -> None:
    server = FakeBedrockServer(FakeResponse(text="answer"), batch_polls_before_done=99)
    client = _bedrock_client(server)
    try:
        handle = await client.submit_batch(_batch(1), target=BEDROCK_TARGET)
        report = await client.cancel_batch(handle)
    finally:
        await client.aclose()

    assert report.status == "cancelled"
    assert report.finished


async def test_an_unconfigured_bucket_refuses_before_anything_is_written() -> None:
    """The bucket is the caller's; AnyInfer neither creates nor guesses one."""
    server = FakeBedrockServer(FakeResponse(text="answer"))
    client = _bedrock_client(server, batch_s3_uri="", batch_role_arn="")
    try:
        with pytest.raises(ai.ConfigError, match="S3 prefix and an execution role"):
            await client.submit_batch(_batch(1), target=BEDROCK_TARGET)
    finally:
        await client.aclose()
    assert server.objects == {}


async def test_a_non_s3_uri_is_refused_rather_than_signed_for_the_wrong_host() -> None:
    server = FakeBedrockServer(FakeResponse(text="answer"))
    client = _bedrock_client(server, batch_s3_uri="https://my-bucket/anyinfer")
    try:
        with pytest.raises(ai.ConfigError, match="must be an s3:// URI"):
            await client.submit_batch(_batch(1), target=BEDROCK_TARGET)
    finally:
        await client.aclose()


async def test_a_bedrock_api_key_alone_cannot_stage_a_batch() -> None:
    """It authenticates the runtime; S3 will not accept it, and saying so beats a 403."""
    server = FakeBedrockServer(FakeResponse(text="answer"))
    client = ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "bedrock",
                api_key="bedrock-api-key",
                options={
                    "region": "us-east-1",
                    "batch_s3_uri": "s3://my-bucket/anyinfer",
                    "batch_role_arn": "arn:aws:iam::1234:role/AnyInferBatch",
                },
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
    )
    try:
        with pytest.raises(ai.ConfigError, match="AWS credentials, not a Bedrock API key"):
            await client.submit_batch(_batch(1), target=BEDROCK_TARGET)
    finally:
        await client.aclose()


def test_partially_completed_is_a_finish_not_a_failure() -> None:
    """The manifest is readable; the lines that failed are reported as failed lines.

    A whole-batch `failed` would discard every answer that did arrive.
    """
    from anyinfer.providers.bedrock import _BEDROCK_BATCH_STATUSES

    assert _BEDROCK_BATCH_STATUSES["PartiallyCompleted"] == "completed"
    assert _BEDROCK_BATCH_STATUSES["Stopped"] == "cancelled"


# ---- the same storage-staged shape on Vertex --------------------------------------------------

from anyinfer.testing.fakes import FakeGeminiServer  # noqa: E402

VERTEX_TARGET = "vertex:gemini-2.5-flash"


def _vertex_client(server: FakeGeminiServer, **options: object) -> ai.AsyncClient:
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "vertex",
                api_key="ya29.fake-access-token",
                options={
                    "project": "my-project",
                    "location": "us-central1",
                    "batch_gcs_uri": "gs://my-bucket/anyinfer",
                    **options,
                },
                transport=server.transport(),
            )
        ],
        use_default_catalog=False,
    )


async def test_vertex_stages_generate_content_bodies_in_the_callers_bucket() -> None:
    server = FakeGeminiServer(FakeResponse(text="answer"))
    client = _vertex_client(server)
    try:
        handle = await client.submit_batch(_batch(2), target=VERTEX_TARGET)
    finally:
        await client.aclose()

    assert len(server.objects) == 1
    key, content = next(iter(server.objects.items()))
    assert key.startswith("anyinfer/anyinfer-")

    staged = [json.loads(line) for line in content.decode().splitlines()]
    # The live generateContent shape, because this adapter *is* the Gemini adapter.
    assert "contents" in staged[0]["request"]

    job = server.requests[0]
    assert job["model"] == "publishers/google/models/gemini-2.5-flash"
    assert job["inputConfig"]["instancesFormat"] == "jsonl"
    assert job["outputConfig"]["predictionsFormat"] == "jsonl"
    assert handle.provider_state["output_prefix"].startswith("gs://my-bucket/anyinfer/")


async def test_a_vertex_line_id_rides_in_the_body_because_the_api_has_no_field_for_it() -> None:
    """The predictions file echoes the request back; that echo is the only pairing channel."""
    server = FakeGeminiServer(FakeResponse(text="answer"))
    client = _vertex_client(server)
    try:
        await client.submit_batch(_batch(2, custom_ids=("row-a", "row-b")), target=VERTEX_TARGET)
    finally:
        await client.aclose()

    staged = [
        json.loads(line)
        for line in next(iter(server.objects.values())).decode().splitlines()
    ]
    assert [entry["request"]["labels"]["anyinfer_line_id"] for entry in staged] == [
        "row-a",
        "row-b",
    ]


async def test_vertex_polls_then_reads_predictions_from_the_directory_the_job_names() -> None:
    """The output directory is timestamped by the API, so it cannot be predicted."""
    server = FakeGeminiServer(FakeResponse(text="answer"), batch_polls_before_done=2)
    client = _vertex_client(server)
    try:
        handle = await client.submit_batch(
            _batch(2, custom_ids=("row-a", "row-b")), target=VERTEX_TARGET
        )
        assert (await client.batch_status(handle)).status == "in_progress"
        finished = await client.batch_status(handle)
        assert finished.finished
        assert finished.completed == 2
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    assert [line.custom_id for line in result.lines] == ["row-a", "row-b"]
    assert [line.result.text for line in result.lines] == ["answer #row-a", "answer #row-b"]
    assert result.lines[0].result.usage.input_tokens == 11


async def test_a_rejected_vertex_line_fails_alone() -> None:
    server = FakeGeminiServer(FakeResponse(text="answer"), batch_failures=1)
    client = _vertex_client(server)
    try:
        handle = await client.submit_batch(_batch(3), target=VERTEX_TARGET)
        result = await client.fetch_batch(handle)
    finally:
        await client.aclose()

    failed = [line for line in result.lines if line.error is not None]
    assert len(failed) == 1
    assert "line rejected" in failed[0].error.detail


async def test_cancelling_a_vertex_job_reports_where_it_landed() -> None:
    server = FakeGeminiServer(FakeResponse(text="answer"), batch_polls_before_done=99)
    client = _vertex_client(server)
    try:
        handle = await client.submit_batch(_batch(1), target=VERTEX_TARGET)
        report = await client.cancel_batch(handle)
    finally:
        await client.aclose()

    assert report.status == "cancelled"


async def test_an_unconfigured_vertex_bucket_refuses_before_anything_is_written() -> None:
    server = FakeGeminiServer(FakeResponse(text="answer"))
    client = _vertex_client(server, batch_gcs_uri="")
    try:
        with pytest.raises(ai.ConfigError, match="caller-owned GCS prefix"):
            await client.submit_batch(_batch(1), target=VERTEX_TARGET)
    finally:
        await client.aclose()
    assert server.objects == {}


async def test_a_non_gcs_vertex_uri_is_refused() -> None:
    server = FakeGeminiServer(FakeResponse(text="answer"))
    client = _vertex_client(server, batch_gcs_uri="https://my-bucket/anyinfer")
    try:
        with pytest.raises(ai.ConfigError, match="must be a gs:// URI"):
            await client.submit_batch(_batch(1), target=VERTEX_TARGET)
    finally:
        await client.aclose()


def test_partially_succeeded_is_a_finish_not_a_failure_on_vertex_too() -> None:
    from anyinfer.providers.vertex import _VERTEX_BATCH_STATUSES

    assert _VERTEX_BATCH_STATUSES["JOB_STATE_PARTIALLY_SUCCEEDED"] == "completed"
    assert _VERTEX_BATCH_STATUSES["JOB_STATE_CANCELLED"] == "cancelled"


def test_all_five_named_providers_are_bound() -> None:
    """E.1.1 named OpenAI, Anthropic, Bedrock, Vertex, and Groq. This is the whole set."""
    from anyinfer.registry import default_registry

    declaring = {
        pid
        for pid in default_registry.known_ids()
        if "batch" in default_registry.get(pid).operations
    }
    assert {"openai", "anthropic", "bedrock", "vertex", "groq"} <= declaring
