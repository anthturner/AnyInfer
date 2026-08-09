"""Conversation compaction as a client policy, identical across every frontend.

A prompt that outgrows its window has two answers: send it somewhere bigger, or make it
smaller. The router has always owned the first; these cover the second, and — the point of
putting it in the client rather than in a frontend — that the Python API, the command line,
and the OpenAI-compatible gateway all get exactly the same behaviour.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import anyinfer as ai
from anyinfer.serve.openai_codec import HISTORY_FIELD, request_from_openai, request_to_openai
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse
from anyinfer.types.capabilities import ModelCapabilities, Sourced
from support import make_client, make_sync_client

BIG = "x" * 10_000

# Big enough that the derived output reserve still leaves an input allowance to compact
# into, small enough that the conversation below provably overflows it. A window with a
# zero allowance is not "too small to fit" but "too small to have an inside", and
# compaction correctly declines it — see `test_a_window_with_no_input_allowance_is_left_alone`.
SMALL_WINDOW = {
    "openai-compat:fake-model-small": ModelCapabilities(
        context_window=Sourced(8_192, "catalog")
    )
}
TWO_WINDOWS = {
    "small:fake-model-small": ModelCapabilities(context_window=Sourced(8_192, "catalog")),
    "large:fake-model-small": ModelCapabilities(context_window=Sourced(200_000, "catalog")),
}
NO_ALLOWANCE = {
    "openai-compat:fake-model-small": ModelCapabilities(
        context_window=Sourced(512, "catalog")
    )
}


def _two_targets(
    small: FakeOpenAIServer, large: FakeOpenAIServer, **kwargs: object
) -> ai.AsyncClient:
    """Two instances of one adapter, so a route can span two window sizes."""
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                alias="small",
                base_url="https://fake.invalid/v1",
                transport=small.transport(),
            ),
            ai.ProviderSettings.of(
                "openai-compat",
                alias="large",
                base_url="https://fake.invalid/v1",
                transport=large.transport(),
            ),
        ],
        **kwargs,  # type: ignore[arg-type]
    )


def _oversized() -> list[ai.Message]:
    """A conversation whose *floor* exceeds the small window above.

    The pre-dispatch gate acts on the estimate's lower bound, not on the planning figure,
    so a fixture that merely overflows the planning estimate would sail straight past it.
    """
    messages = [ai.system("Be brief.")]
    for index in range(5):
        messages.append(ai.user(f"Question {index}. {BIG}"))
        messages.append(ai.assistant(f"Answer {index}. {BIG}"))
    messages.append(ai.user("And finally?"))
    return messages


class Recorder(ai.Observer):
    """Collects every telemetry event."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def on_event(self, event: object) -> None:
        self.events.append(event)


def _reductions(recorder: Recorder) -> list[ai.ContextReduced]:
    return [e for e in recorder.events if isinstance(e, ai.ContextReduced)]


# ---- the policy itself ---------------------------------------------------------------


def test_defaults_do_not_compact() -> None:
    policy = ai.HistoryPolicy()
    assert policy.mode == "last_resort"
    assert policy.enabled
    assert policy.keep_recent == 6


@pytest.mark.parametrize("mode", ["always", "", "LAST_RESORT"])
def test_an_unknown_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValueError, match="history mode"):
        ai.HistoryPolicy(mode=mode)  # type: ignore[arg-type]


def test_a_negative_recent_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="keep_recent"):
        ai.HistoryPolicy(keep_recent=-1)


# ---- SDK: no policy means today's behaviour ------------------------------------------


@pytest.mark.asyncio
async def test_without_a_policy_an_oversized_request_still_fails() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server, capability_overrides=SMALL_WINDOW) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.generate(_oversized(), target="openai-compat:fake-model-small")
    assert not server.requests, "the gate refuses before dispatch"


# ---- proactive -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proactive_shrinks_the_conversation_to_fit_and_succeeds() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    recorder = Recorder()
    async with make_client(
        server,
        capability_overrides=SMALL_WINDOW,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        result = await client.generate(
            _oversized(), target="openai-compat:fake-model-small"
        )

    assert result.text == "hi"
    assert server.requests, "the request was dispatched, not refused"
    sent = server.requests[0]["messages"]
    # Eliding the payloads was enough, so every turn is still present — the shape of the
    # conversation survives even when its bulk does not.
    assert len(sent) == len(_oversized())
    original = sum(len(m.text) for m in _oversized())
    assert sum(len(json.dumps(m)) for m in sent) < original // 4
    assert any("[elided " in json.dumps(m) for m in sent)
    # Compaction stops the moment the request fits, so the least-recent turns are elided
    # and whatever was still affordable is left whole.
    assert any("[elided " not in json.dumps(m) for m in sent[1:-1])
    assert sent[0] == {"role": "system", "content": "Be brief."}
    assert sent[-1]["content"] == "And finally?"


@pytest.mark.asyncio
async def test_proactive_announces_itself() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    recorder = Recorder()
    async with make_client(
        server,
        capability_overrides=SMALL_WINDOW,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        await client.generate(_oversized(), target="openai-compat:fake-model-small")

    events = _reductions(recorder)
    assert len(events) == 1
    assert events[0].strategy == "history"
    assert events[0].omitted_count >= 0
    assert BIG not in repr(events[0]), "the event stays content-free"


@pytest.mark.asyncio
async def test_proactive_leaves_a_fitting_request_alone() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    recorder = Recorder()
    async with make_client(
        server,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="proactive"),
    ) as client:
        await client.generate([ai.user("short")], target="openai-compat:fake-model-small")

    assert not _reductions(recorder), "nothing to compact means nothing is compacted"
    assert server.requests[0]["messages"] == [{"role": "user", "content": "short"}]


@pytest.mark.asyncio
async def test_proactive_spends_the_larger_window_it_never_reaches() -> None:
    # The documented tradeoff: with no overflow left to redirect, the route's
    # larger-window target is never consulted.
    small = FakeOpenAIServer(FakeResponse(text="from small"))
    large = FakeOpenAIServer(FakeResponse(text="from large"))
    async with _two_targets(
        small,
        large,
        capability_overrides=TWO_WINDOWS,
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        result = await client.generate(
            _oversized(),
            route=ai.Route(
                targets=("small:fake-model-small",),
                context_window_targets=("large:fake-model-small",),
            ),
        )
    assert result.text == "from small"
    assert not large.requests


# ---- last resort ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_resort_prefers_a_larger_window_over_losing_history() -> None:
    small = FakeOpenAIServer(FakeResponse(text="from small"))
    large = FakeOpenAIServer(FakeResponse(text="from large"))
    recorder = Recorder()
    async with _two_targets(
        small,
        large,
        capability_overrides=TWO_WINDOWS,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="last_resort", keep_recent=1),
    ) as client:
        result = await client.generate(
            _oversized(),
            route=ai.Route(
                targets=("small:fake-model-small",),
                context_window_targets=("large:fake-model-small",),
            ),
        )

    assert result.text == "from large"
    assert not _reductions(recorder), "the whole conversation fit somewhere; nothing was lost"
    assert len(large.requests[0]["messages"]) == len(_oversized())


@pytest.mark.asyncio
async def test_last_resort_compacts_once_the_route_is_exhausted() -> None:
    server = FakeOpenAIServer(FakeResponse(text="compacted"))
    recorder = Recorder()
    async with make_client(
        server,
        capability_overrides=SMALL_WINDOW,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="last_resort", keep_recent=1),
    ) as client:
        result = await client.generate(
            _oversized(), target="openai-compat:fake-model-small"
        )

    assert result.text == "compacted"
    assert len(_reductions(recorder)) == 1
    assert len(server.requests) == 1, "the retry pass is the only dispatch"


@pytest.mark.asyncio
async def test_last_resort_gives_up_rather_than_looping() -> None:
    # A conversation whose protected messages alone overflow cannot be saved; one
    # compaction pass is attempted and the failure surfaces.
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(
        server,
        capability_overrides=SMALL_WINDOW,
        history=ai.HistoryPolicy(mode="last_resort", keep_recent=40),
    ) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.generate(_oversized(), target="openai-compat:fake-model-small")


@pytest.mark.asyncio
async def test_an_unknown_window_is_never_compacted_against() -> None:
    # Unknown stays unknown: the client will not invent a window to justify discarding
    # a conversation.
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    recorder = Recorder()
    async with make_client(
        server,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        await client.generate(_oversized(), target="openai-compat:fake-model-small")

    assert not _reductions(recorder)
    assert len(server.requests[0]["messages"]) == len(_oversized())


# ---- per-request override ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_request_can_opt_out_of_the_client_policy() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(
        server,
        capability_overrides=SMALL_WINDOW,
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.generate(
                _oversized(),
                target="openai-compat:fake-model-small",
                history=ai.HistoryPolicy(enabled=False),
            )
    assert not server.requests


@pytest.mark.asyncio
async def test_a_request_can_opt_in_where_the_client_did_not() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    async with make_client(server, capability_overrides=SMALL_WINDOW) as client:
        result = await client.generate(
            _oversized(),
            target="openai-compat:fake-model-small",
            history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
        )
    assert result.text == "hi"


# ---- the sync facade behaves identically ---------------------------------------------


def test_the_sync_client_compacts_the_same_way() -> None:
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    with make_sync_client(
        server,
        capability_overrides=SMALL_WINDOW,
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        result = client.generate(_oversized(), target="openai-compat:fake-model-small")
    assert result.text == "hi"
    assert server.requests


# ---- the gateway inherits it, and can be told per request ----------------------------


def test_the_codec_decodes_the_history_extension() -> None:
    _, request, _ = request_from_openai(
        {
            "model": "openai:gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            HISTORY_FIELD: {"mode": "proactive", "keep_recent": 2},
        }
    )
    assert request.history is not None
    assert request.history.mode == "proactive"
    assert request.history.keep_recent == 2


def test_the_extension_does_not_leak_into_provider_options() -> None:
    _, request, _ = request_from_openai(
        {
            "model": "openai:gpt-4o",
            "messages": [],
            HISTORY_FIELD: {"mode": "proactive"},
        }
    )
    assert "*" not in request.provider_options, "the extension is decoded, not passed through"


def test_a_bare_boolean_is_accepted() -> None:
    _, enabled, _ = request_from_openai(
        {"model": "m", "messages": [], HISTORY_FIELD: True}
    )
    _, disabled, _ = request_from_openai(
        {"model": "m", "messages": [], HISTORY_FIELD: False}
    )
    assert enabled.history is not None and enabled.history.enabled
    assert disabled.history is not None and not disabled.history.enabled


@pytest.mark.parametrize(
    "raw",
    [
        {"mode": "whenever"},
        {"keep_recent": "two"},
        {"keep_recent": True},
        {"enabled": "yes"},
        {"unknown_key": 1},
        "proactive",
        7,
    ],
)
def test_a_malformed_extension_is_rejected(raw: object) -> None:
    with pytest.raises(ValueError):
        request_from_openai({"model": "m", "messages": [], HISTORY_FIELD: raw})


def test_the_extension_survives_a_round_trip() -> None:
    body = {
        "model": "openai:gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        HISTORY_FIELD: {
            "enabled": True,
            "mode": "proactive",
            "keep_recent": 2,
            "keep_system": False,
        },
    }
    target, request, stream = request_from_openai(body)
    again = request_to_openai(target, request, stream=stream)
    assert again[HISTORY_FIELD] == body[HISTORY_FIELD]


def test_a_request_without_the_extension_does_not_gain_one() -> None:
    target, request, _ = request_from_openai(
        {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert request.history is None
    assert HISTORY_FIELD not in request_to_openai(target, request)


# ---- the shared config drives all three ----------------------------------------------


def test_a_config_file_carries_the_policy() -> None:
    config = ai.loads_config(
        json.dumps({"history": {"mode": "proactive", "keep_recent": 2, "keep_system": False}})
    )
    assert config.history is not None
    assert config.history.mode == "proactive"
    assert config.history.keep_recent == 2
    assert not config.history.keep_system


def test_a_file_without_the_block_asks_for_no_compaction() -> None:
    assert ai.loads_config("{}").history is None


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"mode": "whenever"}, "history.mode"),
        ({"keep_recent": "two"}, "history.keep_recent"),
        ({"keep_recent": True}, "history.keep_recent"),
        ({"enabled": "yes"}, "history.enabled"),
        ({"nonsense": 1}, "unknown key"),
    ],
)
def test_a_malformed_history_block_is_rejected(block: dict, message: str) -> None:
    with pytest.raises(ai.ConfigError, match=message):
        ai.loads_config(json.dumps({"history": block}))


def test_the_history_block_must_be_an_object() -> None:
    with pytest.raises(ai.ConfigError, match="'history' must be an object"):
        ai.loads_config(json.dumps({"history": "proactive"}))


def test_the_cli_hands_the_policy_to_its_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `anyinfer run` and `anyinfer serve` must not each invent their own reading of the
    # block; both pass config.history straight to the client they build.
    from anyinfer import cli

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "providers": [
                    {"id": "openai-compat", "base_url": "https://fake.invalid/v1"}
                ],
                "history": {"mode": "proactive", "keep_recent": 3},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    seen: dict[str, object] = {}

    class _Spy:
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen.update(kwargs)
            raise SystemExit(0)

    monkeypatch.setattr(ai, "Client", _Spy)
    with pytest.raises(SystemExit):
        cli.main(["run", "hello", "--config", str(config)])
    policy = seen.get("history")
    assert isinstance(policy, ai.HistoryPolicy)
    assert policy.mode == "proactive"
    assert policy.keep_recent == 3


@pytest.mark.asyncio
async def test_a_window_with_no_input_allowance_is_left_alone() -> None:
    # A window smaller than its own output reserve has no inside to compact into.
    # Discarding the conversation would lose it for nothing, so the failure surfaces.
    server = FakeOpenAIServer(FakeResponse(text="hi"))
    recorder = Recorder()
    async with make_client(
        server,
        capability_overrides=NO_ALLOWANCE,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        with pytest.raises(ai.AllTargetsFailedError):
            await client.generate(_oversized(), target="openai-compat:fake-model-small")
    assert not _reductions(recorder)


@pytest.mark.asyncio
async def test_the_tool_loop_inherits_the_policy() -> None:
    # The growing tool transcript is where compaction earns its keep, and `run_tools`
    # forwards to generate(), so it must need no wiring of its own.
    server = FakeOpenAIServer(FakeResponse(text="done"))
    recorder = Recorder()

    def weather(city: str) -> str:
        """Look up the weather."""
        return "sunny"

    async with make_client(
        server,
        capability_overrides=SMALL_WINDOW,
        observers=[recorder],
        history=ai.HistoryPolicy(mode="proactive", keep_recent=1),
    ) as client:
        result = await client.run_tools(
            _oversized(), tools=[weather], target="openai-compat:fake-model-small"
        )
    assert result.text == "done"
    assert len(_reductions(recorder)) == 1
