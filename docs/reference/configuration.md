# Shared configuration

AnyInfer has one JSON configuration format for every integration method. Load it from
Python, pass it to `anyinfer run`, or start the OpenAI-compatible sidecar with it. Provider
identity, credentials, endpoint overrides, and the default route therefore do not drift
between deployments.

```json
{
  "format_version": 1,
  "providers": [
    {"id": "anthropic", "api_key": "env://ANTHROPIC_API_KEY"},
    {"id": "ollama"}
  ],
  "default_route": ["ollama:qwen3:8b", "anthropic:claude-sonnet-4-5"]
}
```

=== "Python SDK"

    ```python
    import anyinfer as ai

    config = ai.load_config("anyinfer.json")
    with ai.Client(config.providers, route=config.route) as client:
        result = client.generate("Explain consistent hashing.")
    ```

=== "CLI"

    ```bash
    anyinfer run "Explain consistent hashing." --config anyinfer.json
    ```

=== "Sidecar"

    ```bash
    anyinfer serve --config anyinfer.json
    # or, from a standalone download:
    anyinfer-serve --config anyinfer.json
    ```

The current `format_version` is `1`. Omitting it is accepted for files written before the
field was introduced. Unknown versions, unknown keys, duplicate instance ids, invalid
types, and files larger than 1 MiB fail with `ConfigError` before a client is created.
The one exception: an entry with `enabled: false` is skipped without validating its other
keys, so a disabled entry can hold settings for a provider that is not installed.

## Provider settings

```python
ai.ProviderSettings.of(
    "openai",
    alias=None,  # instance id; defaults to the provider id
    base_url="https://api.openai.com/v1",  # provider default when omitted
    api_key="env://OPENAI_API_KEY",  # literal, env://, or credential://
    api_version=None,  # Azure and Anthropic
    headers={},  # extra request headers
    options={},  # adapter-specific settings
    timeout_s=120.0,  # default per-request timeout
)
```

The **order** you list providers is the preference order for
[alias resolution](../concepts/targets.md#aliases).

### Configuring one engine more than once

`alias` gives an entry its own identity, so the same engine can be configured several
times; two Azure tenants, a local and a remote Ollama; each with its own endpoint and
credentials. The alias is what a target string names:

```python
client = ai.Client(
    [
        ai.ProviderSettings.of(
            "azure-foundry",
            alias="work",
            base_url="https://work.openai.azure.com",
            api_key="env://WORK_KEY",
        ),
        ai.ProviderSettings.of(
            "azure-foundry",
            alias="lab",
            base_url="https://lab.openai.azure.com",
            api_key="env://LAB_KEY",
        ),
    ]
)

client.generate(messages, target="work:gpt-4o")  # the work tenant, not the lab one
```

Each alias becomes its own adapter with its own connection pool. Omitting `alias` is the
ordinary single-instance case, where the provider id is the instance id. Two entries
sharing an instance id is a `ConfigError`, as is an alias that would shadow a registered
provider id.

### Providers that take a choice of credential

`api_key` is the top-level slot for the *usual* credential. A provider that accepts more
than one kind declares each as its own setup field and reads the extra ones from
`options`. Anthropic is the case in point: a console API key and a claude.ai subscription
token authenticate with different headers, so they are separate fields rather than two
spellings of one.

```python
# An Anthropic API key; sent as x-api-key.
ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")

# A claude.ai OAuth token; sent as a bearer token, with the beta flag the API requires.
# Obtain one with: ant auth print-credentials --access-token
ai.ProviderSettings.of("anthropic", options={"oauth_token": "env://ANTHROPIC_OAUTH_TOKEN"})
```

Supply one or the other; if both are set the OAuth token wins.

**Option values for fields a provider declares as `secret` go through the same credential
resolver as `api_key`**, so they accept `env://` and `credential://` references and are
registered for redaction. Bedrock's explicit AWS credentials work the same way:

```python
ai.ProviderSettings.of(
    "bedrock",
    options={
        "aws_access_key_id": "AKIA…",  # an identifier, passed through
        "aws_secret_access_key": "env://AWS_SECRET_ACCESS_KEY",  # resolved and redacted
    },
)
```

Fields a provider declares as anything *other* than `secret` are passed through verbatim —
resolving them would corrupt any literal value that merely looked like a reference.

To discover what a provider accepts without hardcoding it, read its setup spec; the
`any_of` groups are the ones where one of several fields will do:

```python
setup = ai.default_registry.get("anthropic").setup
[(f.key, f.required) for f in setup.fields]  # declared fields
setup.any_of  # (('api_key', 'oauth_token'),)
setup.requirement_note  # why, in one line
```

### Which fields to actually ask for

Not every declared field is a question. A provider knows its own endpoint, its API
version, and where AWS keeps its credentials; what it cannot know is your key or your
account. The spec draws that line itself, so an application prompting for setup does not
have to infer it from help text:

```python
setup = ai.default_registry.get("openai").setup
[f.key for f in setup.essential_fields]  # ['api_key'] ; ask for these
[f.key for f in setup.advanced_fields]  # ['base_url']; offer these, folded away
```

An advanced field is never required and never part of an `any_of` group, so a form built
from `essential_fields` alone can always be saved. Each one carries the value it falls
back to in `SetupField.default_value` (`https://api.openai.com/v1` here), which is what
lets a collapsed field still say what it will do. Render that value rather than
pre-filling the editor with it: a saved copy of today's default keeps overriding the real
default long after it has moved on.

The two extremes are worth knowing. `ollama`, `vllm`, and the other local engines have no
essential fields at all; there is nothing to fill in. `azure-foundry`, `runpod`, and
anything else whose URL embeds an account or endpoint id keeps `base_url` essential,
because no default could be right.

## Client settings

```python
ai.Client(
    providers,
    registry=None,  # defaults to the process-wide registry
    catalog=None,  # defaults to the bundled catalog
    route=None,  # default route when a call names no target
    observers=[],  # telemetry sinks, registered payload-free
    resolver=None,  # credential resolver chain
    retain_raw=False,  # keep raw provider payloads on results
    repair=None,  # default repair budget
    use_default_catalog=True,  # False disables alias resolution entirely
    estimator=None,  # token counting; defaults to the byte heuristic
    context_gate=True,  # refuse requests that provably cannot fit pre-dispatch
    history=None,  # conversation compaction when a request overflows
    arena=None,  # default fixed-target arena policy
    arenas={},  # named arena policies for CLI/sidecar model strings
    pricing_table=None,  # defaults to the bundled table; see fetch_pricing()
    capability_overrides=None,  # "provider:model"-keyed corrections, strongest layer
    model_dir=None,  # where acquired model weights are stored
)
```

`retain_raw` is off by default because raw payloads carry response text that payload-free
telemetry deliberately omits.

## Per-request options

```python
client.generate(
    messages,
    target="medium",  # or route=
    schema=None,
    tools=(),
    tool_choice="auto",  # "auto" | "none" | "required" | a tool name
    sampling=ai.Sampling(...),
    reasoning=None,  # "minimal" | "low" | "medium" | "high"
    timeout_s=None,  # per attempt; defaults to 120
    repair=None,
    provider_options={},  # namespaced escape hatch
    metadata={},  # opaque, echoed in telemetry
    max_response_bytes=1_048_576,
    arena=None,  # fixed targets and post-run selection
    context=None,  # caller-approved stateless corpus reduction
)
```

`Sampling` fields default to `None`, meaning *provider default*. AnyInfer never invents a
temperature; an unset value is omitted from the wire request entirely.

## Environment variables

| Variable | Effect |
|---|---|
| `ANYINFER_MODEL_DIR` | Override where downloaded models are stored (also `Client(model_dir=...)`). |
| `ANYINFER_RUNTIME_DIR` | Override where llama.cpp runtime variants are installed. |
| `ANYINFER_HARDWARE_CACHE_BYPASS` | Skip the hardware cache entirely, read and write. |
| `ANYINFER_HARDWARE_CACHE_REFRESH` | Ignore a cached profile, re-probe, and rewrite it. |
| `ANYINFER_SERVE_TOKEN` | Bearer token for `anyinfer serve`. |
| `COPILOT_CLI_PATH` | Override Copilot CLI discovery. |

Credential references (`env://NAME`) read any variable you name; there are no magic
credential variable names.

## Generating a file

`anyinfer init` writes a valid configuration from what the machine can already do —
running loopback engines and credential variables that are actually set; plus a runnable
starter program beside it. See [the CLI guide](../guides/cli.md#getting-a-config-file-in-the-first-place).

In Python, the same format is written by `anyinfer.dumps_config` and `anyinfer.dump_config`:

```python
import anyinfer as ai

config = ai.AnyInferConfig(
    providers=(ai.ProviderSettings.of("openai", api_key="env://OPENAI_API_KEY"),),
    route=ai.Route(targets=("openai:gpt-5",)),
)
ai.dump_config(config, "anyinfer.json")  # refuses to replace an existing file
text = ai.dumps_config(config, comments=True)  # the same JSON, with a leading note
```

Round-tripping is the contract: `loads_config(dumps_config(c)) == c` for every
configuration the loader accepts. Two consequences are worth knowing:

- An opt-in policy left entirely at its defaults still writes its block, as `{}`. The
  block's *presence* is what asks for the policy; dropping it would turn "pace this
  provider by whatever it reports" back into "do not pace it at all".
- `comments=True` writes a `_comment` string at the root rather than `//` lines. The
  format is JSON, so a generated file explains itself in something the loader accepts;
  reading it back changes nothing.

The writer emits credential *references* exactly as they were given. It never resolves
one, so no code path exists by which `dump_config` could write key material.

## File format

```json
{
  "format_version": 1,
  "providers": [
    {"id": "anthropic", "api_key": "env://ANTHROPIC_API_KEY"},
    {"id": "ollama"},
    {
      "id": "llama-cpp",
      "options": {"posture": "balanced", "runtime": "cuda"}
    }
  ],
  "default_route": ["anthropic:claude-sonnet-4-5", "ollama:qwen3:8b"]
}
```

Each provider entry needs an `id`. Top-level provider settings are `adapter`, `base_url`,
`api_key`, `api_version`, `headers`, `timeout_s`, and `options`. Setup fields declared by
that provider may also be written directly, or grouped under a `values` object (the shape
setup UIs write); unrecognized fields fail validation. Two more keys exist for
compatibility: `provider_id` is the legacy spelling of `adapter`, and `alias`, when
present, must simply restate the entry's `id`. Credential
references such as `env://ANTHROPIC_API_KEY` are resolved only when the adapter is first
used, so parsing a config never prints or expands a secret.

Set `enabled` to `false` to keep a provider entry in a file without loading it. The demo app
uses that facility and writes its own UI fields alongside the shared fields; the SDK, CLI,
and sidecar deliberately ignore those known demo-only fields (at the root: `targets`,
`system_prompt`, `theme`, and `context_window_tokens`).

### The `adapter` key

`id` is the **instance** id used in target strings. The optional `adapter` key names the
engine behind it, which is what lets one engine be configured more than once:

```json
{
  "providers": [
    {"id": "openai", "api_key": "env://OPENAI_API_KEY"},
    {
      "id": "work-azure",
      "adapter": "azure-foundry",
      "base_url": "https://wumbo.openai.azure.com",
      "api_key": "env://WUMBO_KEY"
    },
    {
      "id": "ollama-local",
      "adapter": "ollama",
      "base_url": "http://127.0.0.1:11434"
    }
  ],
  "default_route": ["openai:gpt-5", "work-azure:gpt-4o"]
}
```

Omitting `adapter` keeps the single-instance spelling exactly as before: the `id` is both
the engine selector and the instance id. A duplicate `id` fails fast with a `ConfigError`.

### The `context` block

Advanced settings for [context reduction](../concepts/context-reduction.md), parsed into a
`ContextTuning`. Every key is a field of that record, so a setting is spelled the same way
in the file, on the command line, and in Python:

```json
{
  "context": {
    "selection_order": "density",
    "diversity": 0.25,
    "split_identifiers": true,
    "query_expansion": true,
    "near_duplicate_threshold": 0.9,
    "compact_fallback": true,
    "salience_weight": 0.5,
    "carry_over_bonus": 0.5
  }
}
```

The block is optional, and every field defaults to the behaviour AnyInfer has always had —
a file without it reduces exactly as before. The values above are what
`ContextTuning.recommended()` sets, which `anyinfer context --preset recommended` applies
without a file.

Read it back with `config.context` and pass it straight through:

```python
config = ai.load_config("anyinfer.json")
reduction = context.select(docs, query, max_tokens=8_000, tuning=config.context)
```

A misspelled setting is a `ConfigError`, not a silent no-op; a tuning key that quietly
does nothing is worse than one that fails loudly. The sidecar reads the same file so one
config serves every frontend, but it does not reduce context itself: it is a wire codec
over a normal client, and reduction is the application's call about its own material.

The full field list is on [`ContextTuning`](api/context.md#advanced-settings).

### The `history` block

Conversation compaction, applied by the client when a request outgrows its target's
window. Because it is a client setting rather than a frontend one, this block makes the
SDK, `anyinfer run`, and the sidecar behave identically:

```json
{
  "history": {"mode": "last_resort", "keep_recent": 6, "keep_system": true}
}
```

`last_resort` compacts only after the route's `context_window_targets` chain is exhausted,
so a larger-window model is always preferred to losing history. `proactive` compacts to fit
the resolved target before dispatch, which avoids a refused preflight but never reaches a
larger-window target further down the route.

Omitting the block means no compaction: an oversized request is rerouted or fails, exactly
as before. Set `"enabled": false` to keep a tuned block switched off.

Sidecar callers can override it per request with the `anyinfer_history` field; see
[the sidecar](../serve/README.md).

### The `arena` and `arenas` blocks

Arena policies fan one request out to fixed targets and select only after the candidates
finish. A default policy and named policies use the same complete field set:

```json
{
  "arena": {
    "targets": ["openai:gpt-5-mini", "anthropic:claude-haiku-4-5"],
    "strategy": "first_valid",
    "concurrency": 2,
    "min_candidates": 1,
    "reveal_targets": false,
    "memoize_tools": "read_only"
  },
  "arenas": {
    "review-panel": {
      "targets": ["openai:gpt-5-mini", "anthropic:claude-haiku-4-5"],
      "strategy": "judge",
      "judge_target": "openai:gpt-5-mini",
      "instructions": "Choose the most precise supported answer."
    }
  }
}
```

Unknown keys fail validation. `anyinfer run --arena-name review-panel` and a sidecar model
string of `review-panel` resolve the named policy without moving orchestration into either
frontend. See [Arena runs](../concepts/arena.md) for cost ceilings, selection rules, tool
loops, and the response evidence envelope.

The sidecar can advertise instance-scoped targets from `/v1/models` by writing them in
instance terms:

```bash
anyinfer serve --config anyinfer.json --expose work-azure:gpt-4o
```

## CLI

```bash
anyinfer init [--output PATH] [--force]         # write this file from what is available
anyinfer serve --host 127.0.0.1 --port 8080 --config anyinfer.json
anyinfer serve --token SECRET --host 0.0.0.0 --allow-remote-exposure
anyinfer serve install --print   # the service definition for this platform; writes nothing
anyinfer run "PROMPT" --config anyinfer.json   # one prompt, then exit
anyinfer doctor [--json]        # detected hardware, recommended tier
anyinfer providers [--json]     # every registered provider and what it needs
anyinfer agents-md >> AGENTS.md # coding-agent instructions for this version
anyinfer context src/ --query "how does auth work?" --max-tokens 8000
anyinfer context src/ --query "…" --max-tokens 8000 --plan   # cost every strategy
```

`run` reads the same config file as `serve`, so one file drives both. See
[run a prompt from the shell](../guides/cli.md) for its flags.

A non-loopback bind requires **both** `--allow-remote-exposure` and a token. The CLI refuses
otherwise, because an unauthenticated LLM gateway on a network is a credential laundering
service.

## Cache and data locations

| Purpose | Windows | macOS | Linux |
|---|---|---|---|
| Hardware cache | `%LOCALAPPDATA%\anyinfer` | `~/Library/Caches/anyinfer` | `$XDG_CACHE_HOME/anyinfer` |
| Model artifacts | `%LOCALAPPDATA%\anyinfer\models` | `~/Library/Application Support/anyinfer/models` | `$XDG_DATA_HOME/anyinfer/models` |

Override the model directory with `options={"model_dir": Path(...)}` on the `llama-cpp`
provider.
