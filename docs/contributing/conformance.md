# The conformance suite

One suite, run against every adapter. It is what makes "the behavior does not change when
you change providers" a checked claim rather than an aspiration.

## Division of labor

- **The conformance suite** proves *our code matches our claims.*
- **The [drift check](https://github.com/anthturner/anyinfer/blob/main/contracts/DRIFT-CHECK.md)** proves *our claims still match
  upstream.*

Both are needed. Passing tests against a protocol that changed last month proves nothing.

## Running it

```bash
pytest tests/test_conformance.py tests/test_ollama.py -q
python workspace.py matrix                 # regenerate the published matrix
```

Each case is its own parametrized test, so a failure names the broken behavior rather than
just "conformance failed".

## The cases

Sixteen, grouped by what they protect:

**Basics** — `list_models`, `health`, `non_streaming`, `streaming`

**The event contract** — `event_ordering` checks all four ordering guarantees; `ttft` checks
that first-token timing is measured and consistent.

**Usage** — `usage` checks internal consistency; `usage_survives_streaming` checks that a
*trailing* usage chunk reaches the result **and** surfaces as an event. That second one
exists because losing late-arriving usage by stopping at `finish_reason` is a widespread,
silent token-undercounting bug in comparable tools.

**Tools** — `tool_calls` and `streaming_tool_calls`, the latter checking that argument
fragments reassemble by index rather than by arrival order.

**Structured output** — `structured_output` and `schema_repair`.

**Failure handling** — `error_mapping`, `retry_after`, `byte_cap`, and
`unknown_finish_reason` (an open enum must normalize, not crash).

## Declaring what you cannot do

```python
supports=Capabilities(reasoning=False, tools=False)
```

An unsupported case is reported `skipped` and renders as ➖ — an honest, documented
limitation. It is deliberately *not* a pass, so the matrix cannot overstate a provider.

## Three modes

| Mode | Proves | Runs |
|---|---|---|
| **fake-server** | We handle each protocol *shape* | Every commit |
| **cassette** | We handle what providers *actually send* | Every commit, for adapters with recorded traffic |
| **live** | It works against the real service | Opt-in, needs credentials |

Fakes are httpx2 transports, not sockets: no ports, no cleanup races, identical on every
platform.

`m365-copilot` is exempt from live mode — its authentication is interactive-only and cannot
run headless. That is recorded rather than worked around.

## Adding a case

Add it to `CONFORMANCE_CASES` in `anyinfer/testing/conformance.py`:

```python
ConformanceCase("my_behavior", "default", "streaming", _case_my_behavior)
#                 name          scenario   capability   check
```

The check raises `AssertionError` with a message explaining what the provider got wrong. Add
a matching scenario to each harness's fake, then regenerate the matrix.

A new case usually means a new *guarantee*, so document it in the relevant concept page too.

## The published matrix

[docs/reference/conformance-matrix.md](../reference/conformance-matrix.md) is **generated**
from a real run. Never hand-edit it: a hand-maintained matrix drifts from reality and then
actively misleads.
