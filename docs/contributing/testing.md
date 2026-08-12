# Testing guide

## Running

```bash
pytest -q                                  # everything
pytest tests/test_routing.py -q            # one module
pytest -k "fallback" -q                    # by name
pytest -q --durations=15                   # find slow tests
```

`filterwarnings = ["error"]` is set: a `ResourceWarning` from a leaked socket or an unclosed
event loop **fails the suite**. That is deliberate — it is how three real concurrency bugs in
the llama-server supervisor were caught.

## Where a test belongs

| Testing | Put it in |
|---|---|
| A behavior every provider must have | `testing/conformance.py` |
| One provider's dialect quirks | `tests/test_<provider>.py` |
| Core logic (routing, schema, events) | The matching `tests/test_*.py` |
| A serve-frontend invariant | `tests/test_openai_roundtrip.py` |

If a behavior should hold for *all* providers, it belongs in the conformance suite so it is
checked for all of them, not just the one you were looking at.

## Fakes, not sockets

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
chunks, and multi-response sequences for retry and repair tests:

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

Recorded real traffic, replayed deterministically. Bodies pass through redaction before
touching disk, so a committed cassette cannot carry a key.

```python
from anyinfer.testing.cassettes import Cassette, CassetteTransport

transport = CassetteTransport(Cassette(path), record=False)
```

## Writing good tests here

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

`asyncio_mode = "auto"` is set — write `async def test_...` with no decorator.

## Subprocess tests

`tests/test_local_server.py` spawns a fake `llama-server` (a Python script behind a
platform-appropriate shim) rather than requiring a real llama.cpp build. It exercises the
supervisor's genuine contract — spawn, poll, distinguish loading from failed, reap, and is
the slowest module in the suite for good reason.
