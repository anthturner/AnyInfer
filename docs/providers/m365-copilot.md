---
provider: m365-copilot
icon: material/microsoft-office
---

# Microsoft 365 Copilot

The most constrained provider in the set, and documented as such rather than papered over.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-no">:material-close: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (prompt-only)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: health (deliberately no-op)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: discovery</span>
</div>

## Setup

```bash
pip install "anyinfer[azure]"
```

```python
client = ai.Client([
    ai.ProviderSettings.of(
        "m365-copilot",
        options={"tenant_id": "...", "client_id": "..."},
    ),
])
result = client.generate(prompt, target="m365-copilot:m365-copilot")
```

Alias: `m365`.

## Interactive authentication only

There is **no client-credential or daemon flow** for this API. Sign-in opens a browser.

Consequences, stated plainly:

- It cannot run headless, in CI, or in a container without a human present.
- It is exempt from live conformance testing.
- `health()` deliberately does *not* trigger a sign-in — a health probe that opens a browser
  window would be a hostile surprise, and the router calls it speculatively.

If you already hold a token, supply it and skip the interactive flow:

```python
ai.ProviderSettings.of("m365-copilot", api_key="env://M365_TOKEN")
```

This is the only workable path for automated use.

## What it supports

| Behavior | Support |
|---|---|
| Streaming | No — a whole response, emitted as one delta |
| Structured output | Prompt-injected only |
| Tools | No |
| Sampling controls | **Ignored by the service** |
| Usage | Generally absent |
| Schema repair | Capped at **one** round trip |

## Ignored parameters are reported

Temperature, top-p, max tokens, stop sequences, tools, and reasoning effort are declared on the descriptor as
ignored, so requesting them emits a `ParameterDropped` telemetry event rather than silently
doing nothing:

```python
class Watch:
    def on_event(self, event):
        if isinstance(event, ai.ParameterDropped):
            log.warning("%s ignored %s", event.target, event.parameter)
```

This is the whole point of that event: a `temperature=0` that had no effect is otherwise
indistinguishable from one that worked.

## One repair attempt, never a loop

The descriptor caps schema repair at a single round trip. Every request here is a Graph
call against a conversation the service keeps state for, behind an interactively-acquired
token — the most expensive request shape in the registry, and the least likely to answer a
repeated question differently.

Asking for more is clamped rather than refused, and the clamp is reported the same way an
ignored parameter is:

```python
result = client.generate(
    prompt, target="m365-copilot:default", schema=PERSON, repair=ai.Repair(max_attempts=3),
)
# ParameterDropped(parameter="repair.max_attempts", reason="... at most 1 ... 3 requested")
```

Prompt-only schema enforcement plus one repair is a real failure rate. Validate
`result.structured` defensively, and prefer a provider with a native structured-output mode
when the shape matters more than the M365 grounding does.

## Notes

- Citations and attributions are retained on `result.raw` rather than normalized — build
  the client with `retain_raw=True` to keep them, since raw payloads are discarded by
  default. v1 has no typed model for them, and inventing one would freeze a shape before
  it is understood.
- A 401/403 hints at both re-authentication *and* the tenant licensing and admin-consent
  requirements, because those are the usual real causes.

## When to use something else

If you need automation, streaming, tools, or sampling control, use another provider. This
adapter exists so that applications with a genuine M365 Copilot requirement can reach it
through the same interface — not because it is a good default.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/m365-copilot.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/m365-copilot.md).
