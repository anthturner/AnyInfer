"""Embedding and reranking: types, provider protocols, routing, and the safety guards."""

from __future__ import annotations

import asyncio

import pytest

import anyinfer as ai
from anyinfer.providers.base import (
    EmbeddingWireRequest,
    EmbeddingWireResult,
    EmbedsText,
    ProviderLifecycle,
    ReranksText,
    RerankWireResult,
    WireRankedItem,
)
from anyinfer.registry import ProviderRegistry
from anyinfer.routing import Retry, Route
from anyinfer.testing import FakeEmbeddingRerankProvider, ScriptedEmbeddingFailure
from anyinfer.types.operations import (
    EmbeddingRequest,
    EmbeddingSpace,
    EmbeddingVector,
    RerankDocument,
    RerankRequest,
)


def _empty_registry() -> ProviderRegistry:
    return ProviderRegistry(load_builtins=False, load_entry_points=False)


# ---- EmbeddingVector validation --------------------------------------------------------


def test_embedding_vector_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        EmbeddingVector(values=())


def test_embedding_vector_rejects_booleans() -> None:
    with pytest.raises(ValueError, match="boolean"):
        EmbeddingVector(values=(True, 0.5))


def test_embedding_vector_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="numeric"):
        EmbeddingVector(values=("x",))  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_embedding_vector_rejects_non_finite(bad: float) -> None:
    with pytest.raises(ValueError, match="NaN or infinite"):
        EmbeddingVector(values=(bad,))


def test_embedding_vector_accepts_valid() -> None:
    vec = EmbeddingVector(values=(0.1, -0.2, 3))
    assert len(vec) == 3


# ---- EmbeddingRequest / RerankRequest validation ---------------------------------------


def test_embedding_request_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        EmbeddingRequest(inputs=())


def test_embedding_request_preserves_duplicates() -> None:
    req = EmbeddingRequest(inputs=("hi", "hi", "hi"))
    assert req.inputs == ("hi", "hi", "hi")


def test_rerank_request_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query"):
        RerankRequest(query="", documents=(RerankDocument(id="a", text="x"),))


def test_rerank_request_rejects_empty_documents() -> None:
    with pytest.raises(ValueError, match="documents"):
        RerankRequest(query="q", documents=())


def test_rerank_request_rejects_duplicate_document_ids() -> None:
    with pytest.raises(ValueError, match="duplicate id"):
        RerankRequest(
            query="q",
            documents=(RerankDocument(id="a", text="x"), RerankDocument(id="a", text="y")),
        )


def test_rerank_request_rejects_non_positive_top_n() -> None:
    with pytest.raises(ValueError, match="top_n"):
        RerankRequest(query="q", documents=(RerankDocument(id="a", text="x"),), top_n=0)


def test_ranked_item_rejects_non_finite_score() -> None:
    from anyinfer.types.operations import RankedItem

    with pytest.raises(ValueError, match="finite"):
        RankedItem(index=0, document_id="a", score=float("nan"))


# ---- EmbeddingSpace compatibility -------------------------------------------------------


def test_embedding_space_same_model_is_compatible() -> None:
    a = EmbeddingSpace(provider_id="p", model="m", model_revision="r1")
    b = EmbeddingSpace(provider_id="p", model="m", model_revision="r1")
    assert a.compatible_with(b)


def test_embedding_space_different_model_is_incompatible() -> None:
    a = EmbeddingSpace(provider_id="p", model="m1")
    b = EmbeddingSpace(provider_id="p", model="m2")
    assert not a.compatible_with(b)


def test_embedding_space_shared_compatibility_id_overrides_model_mismatch() -> None:
    a = EmbeddingSpace(provider_id="p1", model="m1", compatibility_id="shared")
    b = EmbeddingSpace(provider_id="p2", model="m2", compatibility_id="shared")
    assert a.compatible_with(b)


def test_embedding_space_dimensions_alone_is_not_sufficient() -> None:
    a = EmbeddingSpace(provider_id="p", model="m1", dimensions=768)
    b = EmbeddingSpace(provider_id="p", model="m2", dimensions=768)
    assert not a.compatible_with(b)


# ---- provider protocol structural checks ------------------------------------------------


def test_fake_provider_satisfies_lifecycle_and_operation_protocols() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake", embedding_dimensions={"e": 4}, rerank_models=["r"]
    )
    assert isinstance(fake, ProviderLifecycle)
    assert isinstance(fake, EmbedsText)
    assert isinstance(fake, ReranksText)


def test_embed_only_fake_declares_no_rerank_operation() -> None:
    """rerank() exists structurally regardless; served model ids are scoped separately."""
    fake = FakeEmbeddingRerankProvider("fake", embedding_dimensions={"e": 4})
    assert isinstance(fake, EmbedsText)
    assert isinstance(fake, ReranksText)
    assert fake.operations() == frozenset({"embedding"})


# ---- end-to-end dispatch through AsyncClient ---------------------------------------------


def _client_with_fake(fake: FakeEmbeddingRerankProvider) -> ai.AsyncClient:
    registry = _empty_registry()
    fake.register(registry)
    return ai.AsyncClient(
        providers=[ai.ProviderSettings.of(fake.provider_id)],
        registry=registry,
        use_default_catalog=False,
    )


async def test_embed_returns_vectors_in_order_with_space() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 8})
    client = _client_with_fake(fake)
    try:
        result = await client.embed(["hello", "world"], target="fake-embed:small")
        assert len(result.vectors) == 2
        assert all(len(v) == 8 for v in result.vectors)
        assert result.vectors[0].values != result.vectors[1].values
        assert result.space.provider_id == "fake-embed"
        assert result.space.model == "small"
        assert result.space.dimensions == 8
    finally:
        await client.aclose()


async def test_embed_single_string_input_normalizes_to_one_item() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        result = await client.embed("solo", target="fake-embed:small")
        assert len(result.vectors) == 1
    finally:
        await client.aclose()


async def test_embed_zero_inputs_is_a_local_validation_error_with_no_call() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            await client.embed([], target="fake-embed:small")
        assert fake.embed_requests == []
    finally:
        await client.aclose()


async def test_embed_preserves_duplicate_inputs_and_positions() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        result = await client.embed(["dup", "dup", "unique"], target="fake-embed:small")
        assert len(result.vectors) == 3
        assert result.vectors[0].values == result.vectors[1].values
    finally:
        await client.aclose()


async def test_embed_retries_and_records_attempt_trail() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)]
        },
    )
    client = _client_with_fake(fake)
    try:
        route = Route(
            targets=("fake-embed:small",), retry=Retry(max_attempts=2, backoff_base_s=0.0)
        )
        result = await client.embed(["hi"], route=route)
        assert [a.outcome for a in result.attempts] == ["retried", "ok"]
    finally:
        await client.aclose()


async def test_embed_exhausted_retries_raises_all_targets_failed() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)] * 5
        },
    )
    client = _client_with_fake(fake)
    try:
        route = Route(
            targets=("fake-embed:small",), retry=Retry(max_attempts=1, backoff_base_s=0.0)
        )
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.embed(["hi"], route=route)
        assert len(excinfo.value.attempts) == 1
        assert excinfo.value.attempts[0].outcome == "failed"
    finally:
        await client.aclose()


async def test_embed_cross_space_fallback_is_refused_before_dispatch() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4, "other": 4},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)]
        },
    )
    client = _client_with_fake(fake)
    try:
        route = Route(
            targets=("fake-embed:small", "fake-embed:other"),
            retry=Retry(max_attempts=1, backoff_base_s=0.0),
        )
        with pytest.raises(ai.ConfigError, match="fallback to fake-embed:other refused"):
            await client.embed(["hi"], route=route)
        assert [req.model for req in fake.embed_requests] == ["small"]
    finally:
        await client.aclose()


async def test_embed_incompatible_fallback_opt_in_serves_with_warning() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4, "other": 4},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)]
        },
    )
    client = _client_with_fake(fake)
    try:
        route = Route(
            targets=("fake-embed:small", "fake-embed:other"),
            retry=Retry(max_attempts=1, backoff_base_s=0.0),
        )
        result = await client.embed(["hi"], route=route, allow_incompatible_fallback=True)
        assert result.target.model == "other"
        assert any("not safely comparable" in w for w in result.warnings)
        assert any("fake-embed:small" in w for w in result.warnings)
    finally:
        await client.aclose()


async def test_embed_same_target_fallback_needs_no_opt_in() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)]
        },
    )
    client = _client_with_fake(fake)
    try:
        route = Route(
            targets=("fake-embed:small", "fake-embed:small"),
            retry=Retry(max_attempts=1, backoff_base_s=0.0),
            health_gate=False,
        )
        result = await client.embed(["hi"], route=route)
        assert result.target.model == "small"
        assert result.warnings == ()
    finally:
        await client.aclose()


async def test_embed_rejects_target_without_embedding_support() -> None:
    from anyinfer.providers.openai_compat import OpenAICompatAdapter

    registry = _empty_registry()
    registry.register(
        ai.ProviderDescriptor(
            id="gen-only",
            display_name="Gen only",
            factory=OpenAICompatAdapter,
            default_base_url="http://gen-only.invalid",
        )
    )
    client = ai.AsyncClient(
        providers=[ai.ProviderSettings.of("gen-only")],
        registry=registry,
        use_default_catalog=False,
    )
    try:
        with pytest.raises(ai.ConfigError, match="does not support embedding"):
            await client.embed(["hi"], target="gen-only:some-model")
    finally:
        await client.aclose()


async def test_embed_rejects_response_incompatible_with_expected_space() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        wrong_space = EmbeddingSpace(provider_id="somewhere-else", model="other-model")
        with pytest.raises(ai.ConfigError, match="expected embedding space"):
            await client.embed(["hi"], target="fake-embed:small", expected_space=wrong_space)
    finally:
        await client.aclose()


async def test_embed_accepts_response_matching_expected_space() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        matching = EmbeddingSpace(provider_id="fake-embed", model="small")
        result = await client.embed(["hi"], target="fake-embed:small", expected_space=matching)
        assert result.space.model == "small"
    finally:
        await client.aclose()


async def test_embed_vector_count_mismatch_is_rejected() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})

    async def _short_result(req: object) -> EmbeddingWireResult:
        return EmbeddingWireResult(vectors=((0.1, 0.2, 0.3, 0.4),), model="small", dimensions=4)

    fake.embed = _short_result  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="returned 1 vectors"):
            await client.embed(["one", "two"], target="fake-embed:small")
    finally:
        await client.aclose()


async def test_rerank_orders_by_score_descending() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    client = _client_with_fake(fake)
    try:
        result = await client.rerank(
            "capital of France",
            ["Paris is the capital of France.", "Berlin is in Germany."],
            target="fake-embed:ranker",
        )
        assert result.items[0].score >= result.items[1].score
        assert result.items[0].document_id == "0"
    finally:
        await client.aclose()


async def test_rerank_preserves_caller_document_ids() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    client = _client_with_fake(fake)
    try:
        docs = [RerankDocument(id="doc-a", text="Paris"), RerankDocument(id="doc-b", text="Berlin")]
        result = await client.rerank("Paris", docs, target="fake-embed:ranker")
        ids = {item.document_id for item in result.items}
        assert ids == {"doc-a", "doc-b"}
    finally:
        await client.aclose()


async def test_rerank_top_n_truncates() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    client = _client_with_fake(fake)
    try:
        result = await client.rerank(
            "France", ["Paris France", "Berlin Germany", "Madrid Spain"],
            target="fake-embed:ranker", top_n=1,
        )
        assert len(result.items) == 1
    finally:
        await client.aclose()


async def test_rerank_rejects_out_of_range_index() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])

    async def _bad_rerank(req: object) -> RerankWireResult:
        return RerankWireResult(items=(WireRankedItem(index=99, score=1.0),))

    fake.rerank = _bad_rerank  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="out-of-range"):
            await client.rerank("q", ["a", "b"], target="fake-embed:ranker")
    finally:
        await client.aclose()


async def test_rerank_rejects_duplicate_index() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])

    async def _dup_rerank(req: object) -> RerankWireResult:
        return RerankWireResult(
            items=(WireRankedItem(index=0, score=1.0), WireRankedItem(index=0, score=0.5))
        )

    fake.rerank = _dup_rerank  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="more than once"):
            await client.rerank("q", ["a", "b"], target="fake-embed:ranker")
    finally:
        await client.aclose()


async def test_rerank_return_documents_echoes_text() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    client = _client_with_fake(fake)
    try:
        result = await client.rerank(
            "France", ["Paris France"], target="fake-embed:ranker", return_documents=True
        )
        assert result.items[0].text == "Paris France"
    finally:
        await client.aclose()


async def test_rerank_without_return_documents_omits_text() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["ranker"])
    client = _client_with_fake(fake)
    try:
        result = await client.rerank("France", ["Paris France"], target="fake-embed:ranker")
        assert result.items[0].text is None
    finally:
        await client.aclose()


# ---- sync facade -------------------------------------------------------------------------


def test_sync_client_embed_and_rerank() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed", embedding_dimensions={"small": 4}, rerank_models=["ranker"]
    )
    registry = _empty_registry()
    fake.register(registry)
    client = ai.Client(
        providers=[ai.ProviderSettings.of("fake-embed")],
        registry=registry,
        use_default_catalog=False,
    )
    try:
        result = client.embed(["hi"], target="fake-embed:small")
        assert len(result.vectors) == 1

        ranked = client.rerank("q", ["a match q", "no"], target="fake-embed:ranker")
        assert len(ranked.items) == 2
    finally:
        client.close()


# ---- Core-owned batching ----------------------------------------------------------------


def _capable_fake(limit: int = 2, **kwargs: object) -> FakeEmbeddingRerankProvider:
    return FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        embedding_capabilities={"small": ai.EmbeddingCapabilities(max_batch_inputs=limit)},
        **kwargs,  # type: ignore[arg-type]
    )


async def test_embed_splits_against_declared_batch_limit() -> None:
    fake = _capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        result = await client.embed(["a", "b", "c", "d", "e"], target="fake-embed:small")
        assert len(result.vectors) == 5
        assert [len(req.inputs) for req in fake.embed_requests] == [2, 2, 1]
        assert result.usage.input_tokens == 5
    finally:
        await client.aclose()


async def test_embed_batch_override_beats_declared_limit() -> None:
    fake = _capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        await client.embed(
            ["a", "b", "c", "d", "e"],
            target="fake-embed:small",
            batch=ai.BatchPolicy(max_items_override=4),
        )
        assert [len(req.inputs) for req in fake.embed_requests] == [4, 1]
    finally:
        await client.aclose()


async def test_embed_unknown_limit_sends_one_request() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        await client.embed(["a"] * 50, target="fake-embed:small")
        assert len(fake.embed_requests) == 1
    finally:
        await client.aclose()


async def test_embed_unknown_limit_over_ceiling_is_refused_locally() -> None:
    from anyinfer.types.operations import DEFAULT_MAX_EMBEDDING_INPUTS

    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="sanity ceiling"):
            await client.embed(
                ["x"] * (DEFAULT_MAX_EMBEDDING_INPUTS + 1), target="fake-embed:small"
            )
        assert fake.embed_requests == []
    finally:
        await client.aclose()


async def test_embed_allow_split_false_refuses_locally() -> None:
    fake = _capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="allow_split is False"):
            await client.embed(
                ["a", "b", "c"],
                target="fake-embed:small",
                batch=ai.BatchPolicy(allow_split=False),
            )
        assert fake.embed_requests == []
    finally:
        await client.aclose()


async def test_embed_batch_preserves_order_under_staggered_completion() -> None:
    fake = _capable_fake(limit=2)
    inner = fake.embed

    async def staggered(req: EmbeddingWireRequest) -> EmbeddingWireResult:
        delay = 0.05 if req.inputs[0] == "t0" else 0.0
        await asyncio.sleep(delay)
        return await inner(req)

    fake.embed = staggered  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    reference_fake = FakeEmbeddingRerankProvider(
        "fake-embed", embedding_dimensions={"small": 4}
    )
    reference_client = _client_with_fake(reference_fake)
    texts = ["t0", "t1", "t2", "t3", "t4"]
    try:
        result = await client.embed(
            texts, target="fake-embed:small", batch=ai.BatchPolicy(max_concurrency=3)
        )
        for position, text in enumerate(texts):
            reference = await reference_client.embed([text], target="fake-embed:small")
            assert result.vectors[position].values == reference.vectors[0].values
    finally:
        await client.aclose()
        await reference_client.aclose()


async def test_embed_batch_failure_is_all_or_error_with_batch_trail() -> None:
    fake = _capable_fake(
        limit=2,
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)]
        },
    )
    client = _client_with_fake(fake)
    try:
        route = Route(
            targets=("fake-embed:small",), retry=Retry(max_attempts=1, backoff_base_s=0.0)
        )
        with pytest.raises(ai.AllTargetsFailedError) as excinfo:
            await client.embed(["a", "b", "c", "d", "e"], route=route)
        failures = excinfo.value.batch_failures
        assert len(failures) == 3
        assert sum(1 for f in failures if not f.succeeded) == 1
        assert sum(f.item_count for f in failures) == 5
        assert "internal batches failed" in str(excinfo.value)
    finally:
        await client.aclose()


async def test_embed_batch_emits_one_logical_request() -> None:
    class _Collector:
        def __init__(self) -> None:
            self.names: list[str] = []

        def on_event(self, event: object) -> None:
            self.names.append(type(event).__name__)

    fake = _capable_fake(limit=2)
    client = _client_with_fake(fake)
    collector = _Collector()
    client.subscribe(collector)
    try:
        await client.embed(["a", "b", "c", "d", "e"], target="fake-embed:small")
        assert collector.names.count("RequestStarted") == 1
        assert collector.names.count("RequestCompleted") == 1
        assert collector.names.count("AttemptStarted") == 3
    finally:
        await client.aclose()


async def test_embed_batch_cancellation_returns_no_partial_result() -> None:
    fake = _capable_fake(limit=1)
    inner = fake.embed

    async def slow(req: EmbeddingWireRequest) -> EmbeddingWireResult:
        await asyncio.sleep(0.2)
        return await inner(req)

    fake.embed = slow  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        task = asyncio.create_task(
            client.embed(
                ["a", "b", "c"],
                target="fake-embed:small",
                batch=ai.BatchPolicy(max_concurrency=1),
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(fake.embed_requests) < 3
    finally:
        await client.aclose()


def _rerank_capable_fake(limit: int = 2) -> FakeEmbeddingRerankProvider:
    return FakeEmbeddingRerankProvider(
        "fake-embed",
        rerank_models=["rr"],
        rerank_capabilities={"rr": ai.RerankCapabilities(max_documents=limit)},
    )


async def test_rerank_over_limit_is_refused_by_default() -> None:
    fake = _rerank_capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="not globally comparable"):
            await client.rerank("q", ["d1", "d2", "d3"], target="fake-embed:rr")
        assert fake.rerank_requests == []
    finally:
        await client.aclose()


async def test_rerank_cross_batch_opt_in_concatenates_chunk_local_rankings() -> None:
    fake = _rerank_capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        # Scores against "alpha beta": d0=0, d1=0.5, d2=1.0, d3=0, d4=0.5.
        # Chunks of 2: [d0, d1], [d2, d3], [d4]. A global re-sort would put d2 first;
        # chunk-local ordering keeps chunk one's items ahead of it.
        docs = ["gamma delta", "alpha gamma", "alpha beta", "delta", "beta gamma"]
        result = await client.rerank(
            "alpha beta",
            docs,
            target="fake-embed:rr",
            batch=ai.BatchPolicy(rerank_cross_batch=True),
        )
        assert [item.index for item in result.items] == [1, 0, 2, 3, 4]
        assert result.warnings
        assert "not a provider-certified global ordering" in result.warnings[0]
    finally:
        await client.aclose()


async def test_rerank_cross_batch_top_n_is_chunk_local_and_warned() -> None:
    fake = _rerank_capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        docs = ["gamma delta", "alpha gamma", "alpha beta", "delta", "beta gamma"]
        result = await client.rerank(
            "alpha beta",
            docs,
            target="fake-embed:rr",
            top_n=1,
            batch=ai.BatchPolicy(rerank_cross_batch=True),
        )
        assert [item.index for item in result.items] == [1, 2, 4]
        assert "applied within each batch" in result.warnings[0]
    finally:
        await client.aclose()


# ---- run manifests for embed and rerank ---------------------------------------------


async def test_embed_manifest_is_a_projection_of_the_call() -> None:
    """RM.8, operation edition — the manifest and the event stream may not disagree."""

    class _Collector:
        def __init__(self) -> None:
            self.events: list[object] = []

        def on_event(self, event: object) -> None:
            self.events.append(event)

    fake = _capable_fake(limit=2)
    client = _client_with_fake(fake)
    collector = _Collector()
    client.subscribe(collector)
    try:
        result = await client.embed(["a", "b", "c"], target="fake-embed:small")
        m = result.manifest
        assert m is not None
        assert m.operation == "embedding"
        assert m.complete is True
        assert m.embedding_space == result.space
        assert m.route.resolved == str(result.target)
        assert [a.outcome for a in m.attempts] == [a.outcome for a in result.attempts]
        assert m.usage.input_tokens == result.usage.input_tokens == 3

        names = [type(e).__name__ for e in collector.events]
        assert names.count("AttemptStarted") == len(m.attempts) == 2
        assert names.count("AttemptCompleted") == 2
        started = next(e for e in collector.events if type(e).__name__ == "RequestStarted")
        assert started.operation == "embedding"  # type: ignore[attr-defined]

        from anyinfer.manifest import RunManifest

        assert RunManifest.from_dict(m.to_dict()) == m
    finally:
        await client.aclose()


async def test_embed_manifest_can_be_disabled_per_call() -> None:
    fake = _capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        result = await client.embed(["a"], target="fake-embed:small", manifest=False)
        assert result.manifest is None
    finally:
        await client.aclose()


async def test_rerank_manifest_records_warnings_as_notes() -> None:
    fake = _rerank_capable_fake(limit=2)
    client = _client_with_fake(fake)
    try:
        result = await client.rerank(
            "alpha beta",
            ["gamma", "alpha gamma", "alpha beta"],
            target="fake-embed:rr",
            batch=ai.BatchPolicy(rerank_cross_batch=True),
        )
        m = result.manifest
        assert m is not None
        assert m.operation == "rerank"
        assert m.embedding_space is None
        assert m.notes == result.warnings
        assert m.notes and "global ordering" in m.notes[0]
    finally:
        await client.aclose()
