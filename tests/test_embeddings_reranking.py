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


# ---- pricing, billable units, and spend ceilings --------------------------------------


def test_usage_sum_and_merge_carry_search_units() -> None:
    from anyinfer.types.results import Usage

    a = Usage(search_units=1)
    b = Usage(search_units=2)
    assert Usage.sum([a, b]).search_units == 3
    assert a.merge(b).search_units == 2
    assert Usage.sum([a, Usage()]).search_units is None  # unknown part -> unknown total


def test_rerank_cost_computed_from_search_units() -> None:
    from decimal import Decimal

    from anyinfer.capabilities.pricing import compute_operation_cost
    from anyinfer.types.capabilities import ModelCapabilities, Pricing, Sourced
    from anyinfer.types.results import Usage

    caps = ModelCapabilities(
        pricing=Sourced(
            Pricing(
                input_per_1m=Decimal("0"),
                output_per_1m=Decimal("0"),
                per_search_unit=Decimal("0.002"),
            ),
            "catalog",
        )
    )
    assert compute_operation_cost(Usage(search_units=2), caps, "rerank") == Decimal("0.004")
    # No search units reported -> unknown, never token-priced by an invented equivalence.
    assert compute_operation_cost(Usage(input_tokens=50), caps, "rerank") is None


async def test_embed_cost_computed_from_trusted_pricing() -> None:
    from decimal import Decimal

    from anyinfer.types.capabilities import Pricing

    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        pricing={"small": Pricing(input_per_1m=Decimal("100"), output_per_1m=Decimal("0"))},
    )
    client = _client_with_fake(fake)
    try:
        result = await client.embed(["a", "b", "c", "d", "e"], target="fake-embed:small")
        assert result.usage.input_tokens == 5
        assert result.usage.cost_usd == Decimal("0.0005")
        assert result.manifest is not None
        assert result.manifest.usage.cost_usd is not None
        assert Decimal(result.manifest.usage.cost_usd) == Decimal("0.0005")
    finally:
        await client.aclose()


def _spend_client(
    fake: FakeEmbeddingRerankProvider, policy: ai.SpendPolicy, ledger: object
) -> ai.AsyncClient:
    registry = _empty_registry()
    fake.register(registry)
    return ai.AsyncClient(
        providers=[ai.ProviderSettings.of(fake.provider_id)],
        registry=registry,
        use_default_catalog=False,
        spend=policy,
        ledger=ledger,  # type: ignore[arg-type]
    )


async def test_embed_total_spend_ceiling_refuses_the_request_that_crosses_it() -> None:
    from decimal import Decimal

    from anyinfer.capabilities.ledger import SpendLedger
    from anyinfer.types.capabilities import Pricing

    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        pricing={"small": Pricing(input_per_1m=Decimal("100"), output_per_1m=Decimal("0"))},
    )
    ledger = SpendLedger()
    client = _spend_client(fake, ai.SpendPolicy(max_total_usd=Decimal("0.0007")), ledger)
    try:
        first = await client.embed(["a", "b", "c", "d", "e"], target="fake-embed:small")
        assert first.usage.cost_usd == Decimal("0.0005")
        assert ledger.totals().cost == Decimal("0.0005")
        with pytest.raises(ai.SpendLimitError):
            await client.embed(["a", "b", "c", "d", "e"], target="fake-embed:small")
        assert len(fake.embed_requests) == 1  # the refused request never dispatched
    finally:
        await client.aclose()


async def test_rerank_unknown_cost_is_refused_when_the_policy_says_so() -> None:
    from anyinfer.capabilities.ledger import SpendLedger

    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["rr"])
    ledger = SpendLedger()
    client = _spend_client(fake, ai.SpendPolicy(on_unknown="refuse"), ledger)
    try:
        with pytest.raises(ai.SpendLimitError, match="cannot be estimated"):
            await client.rerank("q", ["d1", "d2"], target="fake-embed:rr")
        assert fake.rerank_requests == []
    finally:
        await client.aclose()


async def test_embed_spend_reservation_is_released_on_failure() -> None:
    from decimal import Decimal

    from anyinfer.capabilities.ledger import SpendLedger
    from anyinfer.types.capabilities import Pricing

    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        pricing={"small": Pricing(input_per_1m=Decimal("100"), output_per_1m=Decimal("0"))},
        embedding_failures={
            "small": [ScriptedEmbeddingFailure(kind="rate-limit", retry_after_s=0.0)]
        },
    )
    ledger = SpendLedger()
    client = _spend_client(fake, ai.SpendPolicy(max_total_usd=Decimal("0.0007")), ledger)
    try:
        route = Route(
            targets=("fake-embed:small",),
            retry=Retry(max_attempts=1, backoff_base_s=0.0),
            health_gate=False,
        )
        with pytest.raises(ai.AllTargetsFailedError):
            await client.embed(["a", "b", "c", "d", "e"], route=route)
        assert ledger.reserved() == Decimal(0)
        # With the reservation released, the retry fits under the ceiling and succeeds.
        result = await client.embed(["a", "b", "c", "d", "e"], route=route)
        assert result.usage.cost_usd == Decimal("0.0005")
    finally:
        await client.aclose()


# ---- capability overlay and conjunction -------------------------------------------------


def test_embedding_capabilities_overlay_known_beats_unknown() -> None:
    from anyinfer.types.operations import EmbeddingCapabilities

    base = EmbeddingCapabilities(dimensions=1024, max_batch_inputs=96)
    layered = base.overlay(EmbeddingCapabilities(max_batch_inputs=32, normalized=True))
    assert layered.dimensions == 1024  # unknown in the layer never displaces known
    assert layered.max_batch_inputs == 32  # the later layer wins where it speaks
    assert layered.normalized is True


def test_embedding_conjunction_refuses_to_guess() -> None:
    from anyinfer.types.operations import EmbeddingCapabilities, embedding_conjunction

    a = EmbeddingCapabilities(
        dimensions=1024, max_batch_inputs=96, input_intents=("query", "document")
    )
    b = EmbeddingCapabilities(dimensions=384, max_batch_inputs=32, input_intents=("query",))
    joined = embedding_conjunction([a, b])
    assert joined.dimensions is None  # disagreement is incompatibility, not a bound
    assert joined.max_batch_inputs == 32
    assert joined.input_intents == ("query",)
    # One unknown bound makes the conjunction unknown.
    c = EmbeddingCapabilities(dimensions=384)
    assert embedding_conjunction([a, c]).max_batch_inputs is None


def test_rerank_conjunction_takes_minimum_known_bounds() -> None:
    from anyinfer.types.operations import RerankCapabilities, rerank_conjunction

    a = RerankCapabilities(max_documents=1000, native_top_n=True)
    b = RerankCapabilities(max_documents=100, native_top_n=True)
    joined = rerank_conjunction([a, b])
    assert joined.max_documents == 100
    assert joined.native_top_n is True
    assert rerank_conjunction([a, RerankCapabilities()]).max_documents is None


def test_model_capabilities_operations_field_with_provenance() -> None:
    from anyinfer.types.capabilities import ModelCapabilities, Sourced, conjunction

    embed_only = ModelCapabilities(operations=Sourced(frozenset({"embedding"}), "catalog"))
    both = ModelCapabilities(
        operations=Sourced(frozenset({"generation", "embedding"}), "discovered")
    )
    assert conjunction([embed_only, both]).operations == Sourced(
        frozenset({"embedding"}), "catalog"
    )
    assert conjunction([embed_only, ModelCapabilities()]).operations is None
    layered = ModelCapabilities().overlay(embed_only)
    assert layered.operations is not None
    assert layered.operations.value == frozenset({"embedding"})


# ---- operation-aware surfaces (models, verify, probes, semantic ranker) -----------------


async def test_models_operation_filter_lists_only_known_servers() -> None:
    fake = _capable_fake(limit=2)  # declares static caps for "small" only
    client = _client_with_fake(fake)
    try:
        embedders = await client.models("fake-embed", operation="embedding")
        assert [m.id for m in embedders] == ["small"]
        # An embed-only provider serves no generation models, and unknown support is
        # never guessed into the listing.
        assert await client.models("fake-embed", operation="generation") == ()
        assert await client.models("fake-embed", operation="rerank") == ()
    finally:
        await client.aclose()


async def test_operations_for_reads_model_level_facts() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        rerank_models=["rr"],
        embedding_capabilities={"small": ai.EmbeddingCapabilities(max_batch_inputs=2)},
        rerank_capabilities={"rr": ai.RerankCapabilities(max_documents=10)},
    )
    client = _client_with_fake(fake)
    try:
        assert client.operations_for("fake-embed:small") == frozenset({"embedding"})
        assert client.operations_for("fake-embed:rr") == frozenset({"rerank"})
        # Unknown model on a provider that does not generate: nothing is known.
        assert client.operations_for("fake-embed:mystery") == frozenset()
    finally:
        await client.aclose()


async def test_verify_embedding_spends_one_probe_and_reports_dimensions() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        verification = await client.verify("fake-embed:small", operation="embedding")
        assert verification.ok is True
        assert verification.reached is True
        assert "4 dimensions" in verification.detail
        assert len(fake.embed_requests) == 1
    finally:
        await client.aclose()


async def test_verify_rerank_reports_unsupported_operation_as_not_reached() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    client = _client_with_fake(fake)
    try:
        verification = await client.verify("fake-embed:small", operation="rerank")
        assert verification.ok is False
        assert verification.reached is False
        assert "rerank" in verification.detail
    finally:
        await client.aclose()


async def test_probe_embedding_measures_dimensions_and_normalization() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 6})
    client = _client_with_fake(fake)
    try:
        report = await client.probe_embedding("fake-embed:small")
        assert report.dimensions == 6
        assert report.normalized is True  # the fake emits unit vectors
        assert report.capabilities.dimensions == 6
        assert report.capabilities.normalized is True
    finally:
        await client.aclose()


def test_semantic_ranker_scores_documents_by_path() -> None:
    from anyinfer.context import ContextDocument

    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["rr"])
    registry = _empty_registry()
    fake.register(registry)
    client = ai.Client(
        providers=[ai.ProviderSettings.of("fake-embed")],
        registry=registry,
        use_default_catalog=False,
    )
    try:
        ranker = ai.semantic_ranker(client, "fake-embed:rr")
        documents = [
            ContextDocument.of("match.txt", "alpha beta gamma"),
            ContextDocument.of("miss.txt", "nothing relevant here"),
        ]
        scores = ranker.scores(documents, "alpha beta")
        assert scores["match.txt"] > scores["miss.txt"]
    finally:
        client.close()


def test_select_uses_the_semantic_ranker_for_ordering() -> None:
    from anyinfer.context import ContextDocument, select

    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["rr"])
    registry = _empty_registry()
    fake.register(registry)
    client = ai.Client(
        providers=[ai.ProviderSettings.of("fake-embed")],
        registry=registry,
        use_default_catalog=False,
    )
    try:
        ranker = ai.semantic_ranker(client, "fake-embed:rr")
        documents = [
            # Lexical ranking would favor the path match on query.txt; the semantic
            # ranker (lexical-overlap fake) favors the body match instead.
            ContextDocument.of("zzz.txt", "alpha beta gamma the answer"),
            ContextDocument.of("query.txt", "unrelated body"),
        ]
        reduction = select(
            documents,
            "alpha beta",
            max_tokens=10_000,
            max_documents=1,
            ranker=ranker,
        )
        assert [d.path for d in reduction.documents] == ["zzz.txt"]
        assert len(fake.rerank_requests) == 1
    finally:
        client.close()


# ---- robustness: type hygiene, malformed responses, cancellation, payload leaks ---------


def test_new_frozen_types_compare_by_value() -> None:
    a = EmbeddingRequest(inputs=("x", "y"), input_type="query")
    b = EmbeddingRequest(inputs=("x", "y"), input_type="query")
    assert a == b
    doc = RerankDocument(id="d", text="t")
    assert RerankRequest(query="q", documents=(doc,)) == RerankRequest(
        query="q", documents=(doc,)
    )
    assert ai.BatchPolicy() == ai.BatchPolicy()
    assert EmbeddingSpace(provider_id="p", model="m") == EmbeddingSpace(
        provider_id="p", model="m"
    )


def test_embedding_vector_accepts_integer_float_mixture() -> None:
    vec = EmbeddingVector(values=(1, 0.5, -2))
    assert len(vec) == 3


async def test_embed_rejects_ragged_vector_response() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})

    async def ragged(req: EmbeddingWireRequest) -> EmbeddingWireResult:
        return EmbeddingWireResult(
            vectors=((0.1, 0.2, 0.3, 0.4), (0.1, 0.2)), model="small", dimensions=4
        )

    fake.embed = ragged  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError, match="inconsistent dimensions"):
            await client.embed(["a", "b"], target="fake-embed:small")
    finally:
        await client.aclose()


async def test_single_call_cancellation_returns_no_partial_result() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    inner = fake.embed

    async def slow(req: EmbeddingWireRequest) -> EmbeddingWireResult:
        await asyncio.sleep(0.2)
        return await inner(req)

    fake.embed = slow  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        task = asyncio.create_task(client.embed(["a"], target="fake-embed:small"))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await client.aclose()


async def test_malformed_rerank_error_text_excludes_document_content() -> None:
    secret_text = "confidential-payroll-figures-Q3"
    fake = FakeEmbeddingRerankProvider("fake-embed", rerank_models=["rr"])

    async def bad_index(req: object) -> RerankWireResult:
        return RerankWireResult(items=(WireRankedItem(index=99, score=0.5),))

    fake.rerank = bad_index  # type: ignore[method-assign]
    client = _client_with_fake(fake)
    try:
        with pytest.raises(ai.ConfigError) as excinfo:
            await client.rerank("q", [secret_text], target="fake-embed:rr")
        assert secret_text not in str(excinfo.value)
        assert secret_text not in repr(excinfo.value)
    finally:
        await client.aclose()


def test_sync_facade_embed_from_many_threads() -> None:
    import concurrent.futures

    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    registry = _empty_registry()
    fake.register(registry)
    client = ai.Client(
        providers=[ai.ProviderSettings.of("fake-embed")],
        registry=registry,
        use_default_catalog=False,
    )
    try:
        def call(i: int) -> int:
            result = client.embed([f"text-{i}"], target="fake-embed:small")
            return len(result.vectors)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            counts = list(pool.map(call, range(24)))
        assert counts == [1] * 24
        assert len(fake.embed_requests) == 24
    finally:
        client.close()


async def test_embed_warns_when_declared_capabilities_ignore_the_intent() -> None:
    fake = FakeEmbeddingRerankProvider(
        "fake-embed",
        embedding_dimensions={"small": 4},
        embedding_capabilities={
            "small": ai.EmbeddingCapabilities(max_batch_inputs=96, input_intents=())
        },
    )
    client = _client_with_fake(fake)
    try:
        result = await client.embed(
            ["hello"], target="fake-embed:small", input_type="query"
        )
        assert any("does not distinguish" in w for w in result.warnings)
        # No declared capabilities at all -> unknown support -> no invented warning.
        bare = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
        bare_client = _client_with_fake(bare)
        try:
            silent = await bare_client.embed(
                ["hello"], target="fake-embed:small", input_type="query"
            )
            assert silent.warnings == ()
        finally:
            await bare_client.aclose()
    finally:
        await client.aclose()


async def test_operation_route_serves_embed_without_a_target() -> None:
    fake = FakeEmbeddingRerankProvider("fake-embed", embedding_dimensions={"small": 4})
    registry = _empty_registry()
    fake.register(registry)
    client = ai.AsyncClient(
        providers=[ai.ProviderSettings.of("fake-embed")],
        registry=registry,
        use_default_catalog=False,
        route=Route(targets=("fake-embed:not-an-embedder",)),
        operation_routes={"embedding": Route(targets=("fake-embed:small",))},
    )
    try:
        result = await client.embed(["hello"])
        assert result.target.model == "small"
        # An explicit target still wins over the configured operation route.
        explicit = await client.embed(["hello"], target="fake-embed:small")
        assert explicit.target.model == "small"
    finally:
        await client.aclose()
