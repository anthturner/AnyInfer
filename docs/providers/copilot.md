---
provider: copilot
icon: material/microsoft
---

# GitHub Copilot

The only adapter that is not raw HTTP. Copilot is reached by driving the Copilot CLI as a
subprocess runtime through `github-copilot-sdk`, so there is no wire protocol for AnyInfer
to speak (the slim core grants this one SDK exception, behind an extra).

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: structured output (prompt-only)</span>
<span class="anyinfer-badge anyinfer-badge-no">:material-close: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: health</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: discovery</span>
</div>

## Setup

```bash
pip install "anyinfer[copilot]"
copilot login          # authentication is delegated to the CLI
```

```python
client = ai.Client([ai.ProviderSettings.of("copilot")])
result = client.generate(prompt, target="copilot:gpt-4.1")
```

No API key is handled by AnyInfer — the CLI owns the credential. Override CLI discovery with
`options={"cli_path": "/path/to/copilot"}` or the `COPILOT_CLI_PATH` environment variable.

Alias: `github-copilot`.

## Supported

| Behavior | Support |
|---|---|
| Streaming | SDK event callbacks |
| Structured output | **Prompt-injected only** — no native mode |
| Tools | **Not supported** — declared as ignored, so requesting them emits `ParameterDropped` |
| Usage | Input, output, cache read/write, reasoning tokens |
| Cost | Not reported |

## The `auto` sentinel

```python
result = client.generate(prompt, target="copilot:auto")
```

Copilot picks the model at request time. Capabilities for `auto` are therefore the
**conjunction** across every model it might choose: the minimum of each numeric bound, the
intersection of feature flags. Claiming more would be a promise you could not verify until a
request failed.

See [capabilities](../concepts/capabilities.md#the-auto-sentinel).

## Token calibration

The CLI runtime builds its own request around your prompt — an agent system preamble, its
built-in tool declarations, workspace framing — none of which appears in the messages this
library serializes. Copilot's reported prompt tokens therefore run well above the bytes
sent, and consistently enough to correct for, so the descriptor declares a
[token calibration](../concepts/budgeting.md#when-the-provider-bills-for-more-than-you-sent):
a 2.4× multiplier plus 1,200 flat tokens.

```python
budget = client.budget(messages, target="copilot:auto")
budget.estimate.envelope.tokens  # the harness, counted separately from your prompt
```

It moves the planning figure only, so `budget()` packs conservatively here while the
pre-dispatch gate stays as permissive as it is everywhere else.

## Structured output

Copilot has no structured-output mode, so a schema is described in the prompt and validated
client-side — [the core's fallback path](../concepts/structured-output.md) for providers
without a native mode. You still get a validated `result.structured`;
`structured_mechanism` will read `"prompt"`.

Consider [`repair=ai.Repair(max_attempts=1)`](../concepts/structured-output.md#repair)
here: prompt-only enforcement has a higher first-attempt failure rate than grammar or
json_schema modes.

## Troubleshooting

**`the copilot provider requires the github-copilot-sdk extra`** — `pip install
'anyinfer[copilot]'`.

**`AuthError` mentioning login** — run `copilot login`.

**CLI not found** — install the Copilot CLI and put it on `PATH`, or set
`COPILOT_CLI_PATH`.

## Notes

- Sessions take a system prompt plus one user turn, so prior turns are folded into the user
  prompt with role markers rather than being silently dropped.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/copilot.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/copilot.md).
