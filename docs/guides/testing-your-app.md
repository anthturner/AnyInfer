# Test your application offline

Your application's inference code has behaviour worth testing: it falls back when a
provider is down, it repairs a malformed structured answer, it reduces a corpus to fit a
budget. Testing that normally means either mocking the library — which tests your mocks —
or calling a real provider from CI, which is slow, costs money, and fails for reasons that
have nothing to do with your change.

AnyInfer ships the third option. `anyinfer.testing` gives you a provider whose behaviour
you declare, and pytest fixtures that wire it to a real client. Everything runs in-process:
no sockets, no credentials, no network, and the same result on every machine.

```bash
pip install anyinfer     # the fixtures come with it — no extra to install
```

## Declare a provider, get a real client

The fixtures are available as soon as `anyinfer` is installed. `anyinfer_scripted` builds a
provider; `anyinfer_client` builds a client wired to it.

```python
from anyinfer.testing import ScriptedModel


def test_summarizer_returns_the_models_answer(anyinfer_client, anyinfer_scripted):
    provider = anyinfer_scripted([ScriptedModel("small", text="A one-sentence summary.")])
    client = anyinfer_client(provider)

    result = client.generate("Summarize this", target=provider.target("small"))

    assert result.text == "A one-sentence summary."
```

Everything between your call and that assertion is the real library: the router resolved
the target, the adapter spoke the wire dialect, the core measured the timings.

## Prove your fallback chain works

A scripted model can be told to fail. Failures are consumed in order, then the model
answers normally — so "fails once, then succeeds" is one line.

```python
from anyinfer.testing import ScriptedFailure, ScriptedModel


def test_retries_a_transient_failure(anyinfer_client, anyinfer_scripted):
    provider = anyinfer_scripted(
        [ScriptedModel("flaky", failures=(ScriptedFailure(status=503, retry_after_s=0.0),))]
    )
    client = anyinfer_client(provider)

    result = client.generate("hi", target=provider.target("flaky"))

    assert [attempt.outcome for attempt in result.attempts] == ["retried", "ok"]
```

`retry_after_s=0.0` advertises the header without making your suite wait for it.

## Prove your repair budget converges

`malformed-json` answers with something that will not validate, so the repair loop runs for
real:

```python
from anyinfer.testing import ScriptedFailure, ScriptedModel

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def test_repairs_an_invalid_structured_answer(anyinfer_client, anyinfer_scripted):
    provider = anyinfer_scripted(
        [
            ScriptedModel(
                "structured",
                structured={"answer": "valid on the second try"},
                failures=(ScriptedFailure(kind="malformed-json"),),
            )
        ]
    )
    client = anyinfer_client(provider)

    result = client.generate(
        "extract", target=provider.target("structured"), schema=SCHEMA, repair={"max_attempts": 1}
    )

    assert result.structured == {"answer": "valid on the second try"}
    assert result.repair_attempts == 1
```

## The failures you can script

| `kind` | What the provider does | What it lets you test |
|---|---|---|
| `status` | Returns an HTTP error, optionally with `Retry-After` | Retry, backoff, the attempt trail |
| `truncate` | Cuts the stream mid-event | Partial-response handling, teardown |
| `malformed-json` | Answers with something that fails validation | Schema validation and the repair loop |
| `timeout` | Raises a read timeout | Your timeout handling, without waiting |
| `refusal` | Finishes with `content_filter` | Your content-policy fallback |

## Assert on telemetry

`anyinfer_events` collects the typed event stream. It is payload-free: it never captures
prompt or response text, so adding it to a suite cannot start logging user content.

```python
from anyinfer.events.telemetry import RetryScheduled


def test_emits_a_retry_event(anyinfer_client, anyinfer_scripted, anyinfer_events):
    provider = anyinfer_scripted(
        [ScriptedModel("flaky", failures=(ScriptedFailure(retry_after_s=0.0),))]
    )
    anyinfer_client(provider).generate("hi", target=provider.target("flaky"))

    assert anyinfer_events.of_type(RetryScheduled)
```

## Model capabilities are declarable too

A scripted model states what it supports. Declaring a model *without* JSON support is how
you test what your code does on the weakest structured-output mechanism:

```python
from anyinfer.types.capabilities import Feature, ModelCapabilities, Sourced

ScriptedModel(
    "plain",
    structured={"answer": "ok"},
    capabilities=ModelCapabilities(
        context_window=Sourced(8_192, "catalog"),
        features=Sourced(Feature.STREAMING | Feature.SYSTEM_PROMPT, "catalog"),
    ),
)
```

The result still validates — client-side validation is always authoritative — but
`result.structured_mechanism` reports `prompt` instead of `json_schema`, which is what your
production code will see against a model that cannot do better.

## The fixtures

| Fixture | What it gives you |
|---|---|
| `anyinfer_scripted` | Factory for scripted providers, registered for this test only |
| `anyinfer_client` | Factory for sync clients, closed automatically |
| `anyinfer_async_client` | The same, asynchronous |
| `anyinfer_events` | A payload-free telemetry collector |
| `anyinfer_registry` | The per-test provider registry, if you need it directly |
| `anyinfer_cassette` | Resolves a cassette stored beside your test file |
| `anyinfer_recording` | Whether this run is recording cassettes |

Each test gets its own provider registry, so two tests may register the same provider id
without depending on execution order.

## Recording real traffic

When you do want to test against what a provider *actually* sent, record it once and replay
it forever:

```python
def test_against_recorded_traffic(anyinfer_cassette, anyinfer_recording):
    cassette = anyinfer_cassette("summarize")
    ...
```

Run your suite with `ANYINFER_RECORD_CASSETTES=1` to record; unset it to replay. Recorded
bodies pass through the redaction registry before reaching disk, so a cassette you commit
alongside a test cannot carry a registered credential.
