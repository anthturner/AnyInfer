# Integrating AnyInfer — the procedure

The canonical, tool-neutral procedure for a coding agent adding or changing AnyInfer code
in an application. The Codex skill, the Claude Code skill, and the Copilot prompt are thin
entry points that read this file; nothing in them repeats what is written here.

Read it in full before writing code. It exists because the most predictable guess about
this library — that it is an OpenAI client with more providers — is wrong in ways that
compile, run, and produce plausible output while quietly duplicating work the core already
does.

## Step 0 — establish which version you are working against

```bash
python -c "import anyinfer; print(anyinfer.__version__)"
anyinfer agents-md          # the short instruction fragment for this exact version
```

`anyinfer agents-md` prints the call shape, the traps, and the live provider and extras
lists. Read its output before anything you remember about this library. Append it to the
repository's own instructions if it is not there yet:

```bash
anyinfer agents-md >> AGENTS.md
```

It writes nothing itself — the redirect is yours to make.

## Step 1 — find out what the application already configured

```bash
anyinfer providers            # every registered provider and the fields it needs
cat anyinfer.json             # the shared configuration, if the repo has one
anyinfer agents-md --config anyinfer.json
```

If there is no configuration file, `anyinfer init` writes one from what the machine can
already reach. Do not invent provider ids, model names, or targets: a target that does not
resolve fails at dispatch, and the purpose of the registry is that the answer is
lookupable.

## Step 2 — write the call

One primitive: a request becomes a typed event stream, and the non-streaming call is that
stream drained.

```python
import anyinfer as ai

with ai.Client([ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")]) as client:
    result = client.generate(prompt, target="anthropic:claude-sonnet-4-5")
```

Four things to get right, because each has an obvious wrong version:

- **`target=`, not `model=`.** A target is `provider:model`, split on the *first* colon
  only, so `ollama:qwen3:8b` names the model `qwen3:8b`. A bare string with no colon is a
  catalog alias (`small`, `medium`, `large`).
- **`schema=`, not `response_format=`.** Pass a JSON Schema, a mapping, or a pydantic-style
  model. The strongest mechanism the target supports is chosen for you and the reply is
  validated before it is returned. Add `repair=ai.Repair(max_attempts=1)` if a retry on a
  malformed answer is worth one more call.
- **`route=ai.Route(...)`, not a retry loop.** Retries, backoff, `Retry-After`, fallback
  between targets, and health gating all belong to the router. Every attempt lands on
  `result.attempts` afterwards.
- **`async` first.** `AsyncClient` is the same surface with `await`. The sync `Client`
  wraps it on a background loop; do not build a second synchronous path.

## Step 3 — do not re-implement the core

If the change you are about to make is on this list, the library already does it, tests it,
and reports what it did. Duplicating it produces double retries, double token counting, or
a second answer to a question that already has one.

| Tempting to write | Already exists |
|---|---|
| a retry/backoff wrapper | `ai.Route`, `ai.Retry` |
| a JSON-repair loop | `schema=` plus `repair=ai.Repair(...)` |
| `if provider == "ollama": ...` | registry descriptors; every provider fact is a field |
| a token counter, a price table | `client.budget(...)`, `result.usage` |
| prompt trimming | `anyinfer.context`, `ai.HistoryPolicy` |
| a secret loader | `api_key="env://VAR"`, resolved once and redacted |
| a spend guard | `ai.SpendPolicy` on the client |
| client-side rate limiting | `RateLimits` on the provider instance |

## Step 4: interpret results accurately

- `result.usage.cost_usd` is a `Decimal` or `None`. `None` means the price is unknown, not
  zero. Never coerce it to `0`.
- Capability values are `Sourced[T]`: `.value` plus a `.provenance` of `catalog`,
  `discovered`, `probed`, or `default`. Do not present a defaulted context window as a
  measured one.
- `result.warnings` and the telemetry stream carry degradations: a dropped parameter, a
  weaker structured-output mechanism, a compacted conversation. If the application shows
  results to a user, show these too.

## Step 5 — prove it, offline

The library ships its own test kit, so an integration's fallback, repair, and reduction
paths get real tests with no credentials and no network:

```python
from anyinfer.registry import ProviderRegistry
from anyinfer.testing import ScriptedFailure, ScriptedModel, ScriptedProvider

registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
provider = ScriptedProvider(
    "acme",
    [ScriptedModel("flaky", failures=(ScriptedFailure(status=503, retry_after_s=0.0),))],
)
provider.register(registry)
```

Then verify the real targets answer, which a health check cannot tell you — a credential
can be valid for a model listing and useless for inference:

```bash
anyinfer verify --config anyinfer.json
```

## Step 6 — check the work before reporting it

- Every target you wrote resolves: `anyinfer verify <target>`.
- No credential value appears in any file you changed; only `env://` or
  `credential://system/...` references.
- No retry, validation, cost, or provider-branch logic was added outside the library.
- The application's own tests cover the failure path, not only the success path.

## Where to look next

- <https://anyinfer.dev/llms.txt>: the documentation index, and
  <https://anyinfer.dev/llms-full.txt> for the full text.
- `anyinfer run "..." --dry-run`: what a request would cost and whether it fits.
- The guide behind this procedure:
  [coding agents](https://anyinfer.dev/guides/coding-agents/).
