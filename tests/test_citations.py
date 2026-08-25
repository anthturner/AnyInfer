"""Typed attributions: one `Citation`, three dialects that agree on almost nothing.

Anthropic reports offsets into the *cited document* and quotes the passage; Cohere reports
offsets into its *own answer* and names a source; Gemini reports answer offsets and a URI.
The normalized type is the intersection of what a person rendering an attribution needs,
and every field is optional because no dialect fills them all.

The rule these tests protect hardest is that an absent offset stays absent. A citation
whose offsets defaulted to zero would render as a highlight over the first characters of
an answer the provider never claimed to support — a fabricated claim, not a missing one.
"""

from __future__ import annotations

from typing import Any

import pytest

import anyinfer as ai
from anyinfer._client.wire import build_wire_request, dropped_parameters
from anyinfer.providers.base import ProviderConfig, WireRequest
from anyinfer.registry import default_registry
from anyinfer.serve.openai_codec import (
    CITATIONS_FIELD,
    CITE_DOCUMENTS_FIELD,
    chunk_from_event,
    encode_citation,
    request_from_openai,
    request_to_openai,
)
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced
from anyinfer.types.events import CitationDelta
from anyinfer.types.messages import DocumentPart, Message, Text
from anyinfer.types.results import Citation

# ---- the type --------------------------------------------------------------------------


def test_an_unstated_offset_is_absent_rather_than_zero() -> None:
    """The whole reason every field is optional."""
    citation = Citation(quoted_text="the sky is blue")
    assert citation.start_index is None
    assert citation.end_index is None
    assert citation.span_of("some answer text") == ""


def test_span_of_returns_the_supported_slice_of_the_answer() -> None:
    assert Citation(start_index=4, end_index=9).span_of("the sky is blue") == "sky i"


def test_span_of_clamps_a_providers_off_by_one_rather_than_raising() -> None:
    """A bad offset should cost a short highlight, not a crashed render."""
    assert Citation(start_index=2, end_index=999).span_of("abc") == "c"
    assert Citation(start_index=-5, end_index=2).span_of("abc") == "ab"
    assert Citation(start_index=9, end_index=2).span_of("abc") == ""


# ---- each dialect ------------------------------------------------------------------------


def _adapter(provider_id: str) -> Any:
    return default_registry.get(provider_id).factory(
        ProviderConfig(provider_id=provider_id, base_url="https://fake.invalid/v1")
    )


def _citations(adapter: Any, chunks: list[dict[str, Any]]) -> list[Citation]:
    """Drive an adapter's chunk translator over a scripted stream."""
    state = adapter._stream_state() if hasattr(adapter, "_stream_state") else None
    if state is None:  # each adapter names its own state class
        module = type(adapter).__module__
        import importlib

        state = importlib.import_module(module)._StreamState()
    found: list[Citation] = []
    for chunk in chunks:
        for event in adapter._events_from_chunk(chunk, state):
            if isinstance(event, CitationDelta):
                found.append(event.citation)
    return found


def test_anthropic_derives_the_answer_span_it_never_reports() -> None:
    """Anthropic gives document offsets only, but emits each citation after its text."""
    adapter = _adapter("anthropic")
    found = _citations(
        adapter,
        [
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Blue light scatters."}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "citations_delta",
                    "citation": {
                        "type": "char_location",
                        "cited_text": "Rayleigh scattering",
                        "document_index": 1,
                        "document_title": "Optics",
                        "start_char_index": 40,
                        "end_char_index": 59,
                    },
                },
            },
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " Red does not."}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "citations_delta",
                    "citation": {"cited_text": "longer wavelengths", "document_index": 1},
                },
            },
        ],
    )

    assert len(found) == 2
    assert (found[0].start_index, found[0].end_index) == (0, 20)
    assert found[0].quoted_text == "Rayleigh scattering"
    assert found[0].document_index == 1
    assert found[0].title == "Optics"
    # The second picks up where the first left off, which is the documented semantics.
    assert (found[1].start_index, found[1].end_index) == (20, 34)


def test_anthropic_document_offsets_never_masquerade_as_answer_offsets() -> None:
    """`start_char_index` counts into the source; reporting it as an answer offset lies."""
    adapter = _adapter("anthropic")
    found = _citations(
        adapter,
        [
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "citations_delta",
                    "citation": {"cited_text": "x", "document_index": 0, "start_char_index": 900},
                },
            },
        ],
    )
    assert found[0].end_index == 2, "the answer is two characters long, whatever the source says"


def test_cohere_answer_offsets_map_straight_across() -> None:
    adapter = _adapter("cohere")
    found = _citations(
        adapter,
        [
            {
                "type": "citation-start",
                "index": 0,
                "delta": {
                    "message": {
                        "citations": {
                            "start": 5,
                            "end": 12,
                            "text": "scatters",
                            "sources": [{"type": "document", "id": "doc:2", "document": {"title": "Optics"}}],
                        }
                    }
                },
            }
        ],
    )
    assert len(found) == 1
    assert (found[0].start_index, found[0].end_index) == (5, 12)
    assert found[0].title == "Optics"


def test_gemini_emits_each_cumulative_source_exactly_once() -> None:
    """`citationMetadata` resends the whole list per chunk, not the new entries."""
    adapter = _adapter("gemini")

    def chunk(count: int) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": "x"}]},
                    "citationMetadata": {
                        "citationSources": [
                            {"startIndex": i, "endIndex": i + 3, "uri": f"https://x/{i}"}
                            for i in range(count)
                        ]
                    },
                }
            ]
        }

    found = _citations(adapter, [chunk(1), chunk(2), chunk(2), chunk(3)])
    assert [c.uri for c in found] == ["https://x/0", "https://x/1", "https://x/2"]


@pytest.mark.parametrize("provider_id", ["anthropic", "cohere", "gemini"])
def test_a_malformed_citation_is_skipped_rather_than_crashing_a_generation(
    provider_id: str,
) -> None:
    """Attributions are advisory output; losing one must not fail an answer."""
    adapter = _adapter(provider_id)
    chunks: list[dict[str, Any]] = [
        {"type": "content_block_delta", "index": 0, "delta": {"type": "citations_delta", "citation": "nonsense"}},
        {"type": "citation-start", "index": 0, "delta": {"message": {"citations": None}}},
        {"candidates": [{"content": {"parts": []}, "citationMetadata": {"citationSources": ["nope"]}}]},
    ]
    assert _citations(adapter, chunks) == []


# ---- the request-side opt-in ---------------------------------------------------------------


def test_anthropic_turns_citations_on_per_document_only_when_asked() -> None:
    """A model does not volunteer citations, and a cited answer bills differently."""
    adapter = _adapter("anthropic")
    message = Message(
        role="user",
        content=(Text("summarize"), DocumentPart(data=b"%PDF", media_type="application/pdf")),
    )

    off = adapter.build_payload(WireRequest(model="m", messages=(message,)))
    document = off["messages"][0]["content"][1]
    assert "citations" not in document

    on = adapter.build_payload(
        WireRequest(model="m", messages=(message,), cite_documents=True)
    )
    assert on["messages"][0]["content"][1]["citations"] == {"enabled": True}


def test_a_target_that_cannot_cite_says_so() -> None:
    request = ai.GenerationRequest(messages=(ai.user("hi"),), cite_documents=True)
    dropped = dict(dropped_parameters(request, default_registry.get("openai-compat")))
    assert "cite_documents" not in dropped, "an unknown capability is not a trusted absence"

    known = ModelCapabilities(features=Sourced(Feature.STREAMING, "catalog"))
    dropped = dict(dropped_parameters(request, default_registry.get("openai-compat"), known))
    assert "cite_documents" in dropped


def test_the_flag_only_reaches_a_model_whose_capabilities_permit_it() -> None:
    request = ai.GenerationRequest(messages=(ai.user("hi"),), cite_documents=True)
    descriptor = default_registry.get("anthropic")
    target = ai.ResolvedTarget(provider_id="anthropic", model="m")

    trusted_without = ModelCapabilities(features=Sourced(Feature.STREAMING, "catalog"))
    assert not build_wire_request(request, target, descriptor, capabilities=trusted_without).cite_documents

    trusted_with = ModelCapabilities(
        features=Sourced(Feature.STREAMING | Feature.CITATIONS, "catalog")
    )
    assert build_wire_request(request, target, descriptor, capabilities=trusted_with).cite_documents


def test_nothing_is_requested_when_the_caller_did_not_ask() -> None:
    request = ai.GenerationRequest(messages=(ai.user("hi"),))
    descriptor = default_registry.get("anthropic")
    target = ai.ResolvedTarget(provider_id="anthropic", model="m")
    assert not build_wire_request(request, target, descriptor).cite_documents
    assert "cite_documents" not in dict(dropped_parameters(request, descriptor))


# ---- the wire extension ---------------------------------------------------------------------


def test_the_request_flag_round_trips_through_the_codec() -> None:
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], CITE_DOCUMENTS_FIELD: True}
    _, request, _ = request_from_openai(body)
    assert request.cite_documents is True
    assert request_to_openai("m", request)[CITE_DOCUMENTS_FIELD] is True


def test_a_mistyped_flag_is_refused_rather_than_defaulted() -> None:
    body = {"model": "m", "messages": [], CITE_DOCUMENTS_FIELD: "true"}
    with pytest.raises(ValueError, match=CITE_DOCUMENTS_FIELD):
        request_from_openai(body)


def test_a_stock_client_that_sends_nothing_gets_nothing_back() -> None:
    _, request, _ = request_from_openai({"model": "m", "messages": []})
    assert request.cite_documents is False
    assert CITE_DOCUMENTS_FIELD not in request_to_openai("m", request)


def test_encoding_omits_every_field_the_provider_did_not_state() -> None:
    """Nulls and zeros would both read as claims the provider never made."""
    assert encode_citation(Citation()) == {}
    assert encode_citation(Citation(start_index=0, end_index=4)) == {
        "start_index": 0,
        "end_index": 4,
    }
    assert encode_citation(Citation(uri="https://x", title="T")) == {"uri": "https://x", "title": "T"}


def test_a_streamed_citation_gets_its_own_frame() -> None:
    chunk = chunk_from_event(
        CitationDelta(Citation(start_index=1, end_index=4, uri="https://x")),
        model="m",
    )
    assert chunk is not None
    assert chunk["choices"][0]["delta"][CITATIONS_FIELD] == [
        {"start_index": 1, "end_index": 4, "uri": "https://x"}
    ]
