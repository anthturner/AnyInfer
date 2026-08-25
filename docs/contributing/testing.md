# Testing Guide

How to run and write tests for AnyInfer itself. If you are testing an application that
*uses* AnyInfer, the guide is
[test your application offline](../guides/testing-your-app.md); the fakes it teaches are
the same public [`anyinfer.testing`](../reference/api/testing.md) package this suite is
built on.

## Running

Two tracks, because the gate and the inner loop want different things.

```bash
workspace test                             # fast track — seconds
workspace test --provider cohere           # one provider's modules + shared invariants
workspace check                            # the gate: everything, plus lint/types/docs
```

`workspace test` cannot run the whole suite, by design. `check` runs
[the quality gates](README.md#the-quality-gates) and is the only thing that tells you the
suite passes, so there is exactly one answer to "is it green"; `test` tells you the code
you are editing still works, which is a different question.

The fast track skips two markers:

| Marker | What it covers | Run it when |
|---|---|---|
| `exhaustive` | The full preset matrix: eighty-six presets through every conformance case. Half the suite's wall time, and it re-proves the *shared* OpenAI dialect. | You changed `openai_compat.py`, a preset entry, or the conformance suite itself. |
| `slow` | Packaging and subprocess builds. | Before committing; `check` runs it. |

Adding or editing one adapter changes nothing either marker covers, which is the point:
that work needs its own module and the shared invariants, not the other twenty adapters.

Everything runs in parallel by default (`pytest-xdist`, `-n auto`), which is worth a ~7x
speedup: every test builds its own in-process fakes, so there is nothing to
share and nothing to serialize on. Pass `-j0` to debug in a single process.

Raw pytest still works, and is what you want for a single test:

```bash
pytest -q -n auto                          # everything, parallel
pytest tests/test_routing.py -q            # one module
pytest -k "fallback" -q                    # by name
pytest -q --durations=15                   # find slow tests
```

`filterwarnings = ["error"]` is set: a `ResourceWarning` from a leaked socket or an
unclosed event loop fails the suite. That strictness caught three real concurrency bugs
in the llama-server supervisor.

## Where a Test Belongs

| Testing | Put it in |
|---|---|
| A behavior every provider must have | `testing/conformance.py` ([the conformance suite](conformance.md)) |
| One provider's dialect quirks | `tests/test_<provider>.py` |
| Core logic (routing, schema, events) | The matching `tests/test_*.py` |
| A serve-frontend invariant | `tests/test_openai_roundtrip.py` |

If a behavior should hold for *all* providers, it belongs in the conformance suite so it is
checked for all of them, not just the one you were looking at.

## Fakes, Not Sockets

```python
from anyinfer.testing.fakes import FakeOpenAIServer, FakeResponse

server = FakeOpenAIServer(FakeResponse(text="hello", finish_reason="stop"))
client = ai.AsyncClient(
    [
        ai.ProviderSettings.of(
            "openai-compat", base_url="https://fake.invalid/v1", transport=server.transport()
        ),
    ]
)
```

Fakes are httpx2 transports: no ports, no cleanup races, identical on every platform. They
can be scripted for errors, malformed SSE, servers that ignore `stream`, omitted usage
chunks, and multi-response sequences for retry and repair tests. The full fake-server
surface is in [the testing API](../reference/api/testing.md).

```python
FakeOpenAIServer(
    [
        FakeResponse(status=503),  # first attempt fails
        FakeResponse(text="recovered"),  # retry succeeds
    ]
)
```

Assert on what was actually sent:

```python
assert server.requests[0]["temperature"] == 0.3
assert server.call_count == 2
```

## Cassettes

Recorded real traffic, replayed deterministically; bodies pass through redaction before
touching disk, so a committed cassette cannot carry a key. The record, replay, and audit
API is under [recording](../reference/api/testing.md#recording), and
[contributing a cassette](conformance.md#contributing-a-cassette) covers the workflow.

## Writing Good Tests Here

**Name the behavior, not the function.**

```python
def test_unknown_memory_is_not_confident() -> None: ...  # yes
def test_recommend_alias_2() -> None: ...  # no
```

**Explain non-obvious assertions.** A one-line docstring on a test that encodes a subtle rule
saves the next reader a lot of guessing:

```python
def test_an_active_stream_is_never_collected() -> None:
    """A long generation with no *new* requests is not idle — the classic false-idle kill."""
```

**Assert the message, not just the type**, when the message is the feature:

```python
assert excinfo.value.hint is not None
assert "anyinfer[keyring]" in excinfo.value.hint
```

**Test the failure mode you are defending against.** Most of the sharpest tests in this
suite exist because a comparable tool shipped that exact bug.

## Async

`asyncio_mode = "auto"` is set; write `async def test_...` with no decorator.

## Subprocess Tests

`tests/test_local_server.py` spawns a fake `llama-server` (a Python script behind a
platform-appropriate shim) rather than requiring a real llama.cpp build. It exercises the
supervisor's real contract: spawn, poll, distinguish loading from failed, reap. Since it
drives actual subprocesses, it is the slowest module in the suite.
