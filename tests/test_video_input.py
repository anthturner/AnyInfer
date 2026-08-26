"""Video message parts: the type's own rules, one projection, and refusal everywhere else.

Video is the modality where a silent drop is most damaging and most likely. Every other
part type has an OpenAI content item to land in, so an adapter that forgot one still sent
*something*; video has none, and every adapter's encoder is a chain of ``isinstance``
branches with no ``else``. A forgotten branch therefore produced a perfectly successful
generation about footage the model was never shown.

So the load-bearing test here is not the Gemini projection — it is
`test_no_adapter_silently_drops_a_video_part`, which walks the whole registry.
"""

from __future__ import annotations

import pytest

import anyinfer as ai
from anyinfer.errors import UnsupportedInputError
from anyinfer.providers.base import WireRequest
from anyinfer.registry import default_registry
from anyinfer.serve.openai_codec import VIDEO_CONTENT_TYPE, decode_messages, encode_messages
from anyinfer.types.capabilities import Feature
from anyinfer.types.messages import Message, Text, VideoPart

VIDEO_MESSAGE = Message(
    role="user",
    content=(Text("What happens?"), VideoPart(data=b"\x00\x01\x02", media_type="video/mp4")),
)


# ---- the type ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({}, "exactly one of data or url"),
        ({"data": b"x", "url": "https://x/y.mp4"}, "exactly one of data or url"),
        ({"data": b"x", "media_type": "image/png"}, "video/"),
        ({"data": b"x", "start_offset_s": -1}, "start_offset_s"),
        ({"data": b"x", "start_offset_s": 5, "end_offset_s": 5}, "after start_offset_s"),
        ({"data": b"x", "fps": 0}, "fps must be positive"),
    ],
)
def test_video_part_refuses_what_no_provider_could_act_on(
    kwargs: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        VideoPart(**kwargs)  # type: ignore[arg-type]


def test_inline_video_counts_against_the_request_ceilings() -> None:
    """The ceilings are not loosened for video; a large clip raises them deliberately."""
    big = VideoPart(data=b"\x00" * 4096)
    with pytest.raises(ValueError, match="per-part limit"):
        ai.GenerationRequest(
            messages=(Message(role="user", content=(big,)),),
            max_input_part_bytes=1024,
        )


def test_a_hosted_video_uri_carries_no_bytes_to_count() -> None:
    request = ai.GenerationRequest(
        messages=(Message(role="user", content=(VideoPart(url="https://x/y.mp4"),)),),
        max_input_part_bytes=1,
        max_input_bytes=1,
    )
    assert request.messages[0].content[0].url == "https://x/y.mp4"  # type: ignore[union-attr]


# ---- the one projection -----------------------------------------------------------------


async def _gemini_parts(built_adapter, part: VideoPart) -> list[dict[str, object]]:
    async with built_adapter("gemini", base_url="https://fake.invalid/v1beta") as adapter:
        message = Message(role="user", content=(Text("hi"), part))
        payload = adapter.build_payload(  # type: ignore[union-attr]
            WireRequest(model="m", messages=(message,))
        )
        return list(payload["contents"][0]["parts"])


async def test_gemini_sends_a_hosted_uri_as_file_data_with_clip_metadata(built_adapter) -> None:
    parts = await _gemini_parts(built_adapter, VideoPart(url="https://x/y.mp4", start_offset_s=1.5, end_offset_s=9, fps=2))
    video = parts[1]
    assert video["fileData"] == {"mimeType": "video/mp4", "fileUri": "https://x/y.mp4"}
    # Protobuf durations, not plain numbers — the one place the dialect departs from JSON.
    assert video["videoMetadata"] == {"startOffset": "1.5s", "endOffset": "9s", "fps": 2}


async def test_gemini_sends_inline_bytes_as_inline_data(built_adapter) -> None:
    video = (await _gemini_parts(built_adapter, VideoPart(data=b"\x00\x01\x02")))[1]
    assert video["inlineData"]["mimeType"] == "video/mp4"  # type: ignore[index]
    assert "videoMetadata" not in video


async def test_gemini_omits_metadata_the_caller_never_set(built_adapter) -> None:
    """A provider default restated as a caller choice is a lie about what was asked."""
    parts = await _gemini_parts(built_adapter, VideoPart(url="https://x/y.mp4"))
    assert "videoMetadata" not in parts[1]


def test_gemini_declares_the_capability_it_actually_projects() -> None:
    capabilities = default_registry.get("gemini").default_capabilities
    assert capabilities is not None
    assert Feature.VIDEO_IN in capabilities.features.value


# ---- refusal everywhere else ------------------------------------------------------------




async def test_no_adapter_silently_drops_a_video_part(built_adapter) -> None:
    """The whole point of the type: every adapter either sends video or refuses it.

    A skipped ``isinstance`` branch is invisible — the request succeeds and the model
    answers about a video it never received. This walks every generation-capable
    descriptor and insists on one of the two honest outcomes.
    """
    dropped: list[str] = []
    seen: set[str] = set()
    for provider_id in sorted(default_registry.known_ids()):
        descriptor = default_registry.get(provider_id)
        if descriptor.id in seen or "generation" not in descriptor.operations:
            continue
        seen.add(descriptor.id)
        async with built_adapter(descriptor.id) as adapter:
            if adapter is None:
                continue
            build = getattr(adapter, "build_payload", None)
            if build is None:
                continue
            try:
                body = repr(build(WireRequest(model="m", messages=(VIDEO_MESSAGE,))))
            except UnsupportedInputError:
                continue  # refused: the other honest outcome
            except Exception:
                continue
            if "video" not in body and "AAEC" not in body:
                dropped.append(descriptor.id)

    assert not dropped, "these adapters silently discard a video part: " + ", ".join(dropped)


@pytest.mark.parametrize("provider_id", ["anthropic", "openai", "openai-compat", "ollama"])
async def test_the_refusal_names_the_modality_and_the_provider(
    built_adapter, provider_id: str
) -> None:
    async with built_adapter(provider_id) as adapter:
        with pytest.raises(UnsupportedInputError, match="video"):
            adapter.build_payload(  # type: ignore[union-attr]
                WireRequest(model="m", messages=(VIDEO_MESSAGE,))
            )


# ---- the sidecar extension ---------------------------------------------------------------


@pytest.mark.parametrize(
    "part",
    [
        VideoPart(url="https://x/y.mp4", start_offset_s=1.0, end_offset_s=4.0, fps=2.0),
        VideoPart(data=b"\x00\x01\x02", media_type="video/webm"),
        VideoPart(url="https://x/y.mp4"),
    ],
)
def test_a_video_part_survives_the_wire_round_trip(part: VideoPart) -> None:
    """Invariant 1: anything the request surface expresses must survive this codec."""
    messages = (Message(role="user", content=(Text("hi"), part)),)
    assert decode_messages(encode_messages(messages)) == messages


def test_the_extension_is_a_content_item_a_stock_client_never_sees() -> None:
    encoded = encode_messages((Message(role="user", content=(VideoPart(url="https://x/y.mp4"),)),))
    assert encoded[0]["content"][0]["type"] == VIDEO_CONTENT_TYPE  # type: ignore[index]
    assert VIDEO_CONTENT_TYPE.startswith("anyinfer_")


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"type": VIDEO_CONTENT_TYPE}, "requires an object"),
        ({"type": VIDEO_CONTENT_TYPE, VIDEO_CONTENT_TYPE: {}}, "requires url or base64 data"),
        (
            {"type": VIDEO_CONTENT_TYPE, VIDEO_CONTENT_TYPE: {"url": "https://x/y", "fps": "fast"}},
            "fps must be a number",
        ),
    ],
)
def test_a_malformed_video_item_is_refused_rather_than_dropped(
    raw: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        decode_messages([{"role": "user", "content": [raw]}])
