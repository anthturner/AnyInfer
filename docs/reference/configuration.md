# Shared Configuration

AnyInfer has one JSON configuration format for every integration method: load it from
Python with `load_config`, pass it to `anyinfer run`, or start the OpenAI-compatible
sidecar with it; each path is walked through in [the guides](../guides/README.md).
Since every deployment reads the same file, provider identity, credentials, endpoint
overrides, and the default route do not drift between them. Full API signatures for the
loader and the validated config object are in
[the configuration API](api/configuration.md).

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

The current `format_version` is `1`. Omitting it is accepted for files written before the
field was introduced. Unknown versions, unknown keys, duplicate instance ids, invalid
types, and files larger than 1 MiB fail with `ConfigError` before a client is created.
The one exception: an entry with `enabled: false` is skipped without validating its other
keys, so a disabled entry can hold settings for a provider that is not installed. The
demo app writes a few UI-only fields of its own alongside the shared ones; the SDK, CLI,
and sidecar ignore them. See [the demo app guide](../guides/demo-app.md).

## Provider Settings

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

The order providers are listed in is the preference order for
[alias resolution](../concepts/targets.md#aliases).

### Proxies, Private CAs, and mTLS

Three optional per-instance keys cover TLS-intercepting proxies and private certificate
authorities — the environments that most often break an otherwise working install:

```json
{
  "id": "openai",
  "api_key": "env://OPENAI_API_KEY",
  "proxy": "http://corp-proxy:3128",
  "verify": "/etc/ssl/corp-ca.pem",
  "client_cert": ["/etc/ssl/client.pem", "/etc/ssl/client.key"]
}
```

- **`proxy`** routes this instance's traffic through a proxy. Omit it to keep the standard
  `HTTPS_PROXY`/`NO_PROXY` environment behavior, which is the default.
- **`verify`** takes a CA-bundle path for a private or intercepting CA, or `false` to
  disable verification entirely. `true` is the default and is not stored.
- **`client_cert`** is a combined PEM path, or `[cert, key]`, or `[cert, key, password]`.

They are **per provider instance** on purpose: one provider can trust a corporate CA while
another keeps the public roots, which a process-wide environment variable cannot express.

!!! warning "`verify: false` disables certificate checking"
    It makes the connection interceptable by anything on the path. Point `verify` at the
    CA bundle instead — that is what it is for, and it keeps verification on.

These are ignored when a `transport` is supplied in code, since a caller bringing its own
transport has taken over connection handling; that is what the offline test modes do.

### URLs in Configuration Are Trusted Input

AnyInfer fetches `base_url`, [MCP server](#the-mcp-block) endpoints, and model-source URLs
as given. It does not filter them by host: a URL pointing at `localhost`, at a private
range, or at a cloud metadata endpoint such as `169.254.169.254` is fetched like any
other, and a `file://` model source reads the local path it names. This is deliberate —
pointing AnyInfer at a service on your own network is the normal case for Ollama, LM
Studio, vLLM, and a self-hosted gateway, and a blocklist would break it.

The assumption is that **configuration is trusted**: written by the operator, not by a
user of the application. It holds for a config file under your control, and for the
sidecar, whose `model` strings resolve only to already-configured providers and so cannot
introduce a new URL.

It stops holding the moment lower-trust input reaches any of these values — a multi-tenant
application letting a customer supply a `base_url`, an MCP endpoint, or a model source. If
you build that, validate the URL against your own allowlist before it reaches
`ProviderSettings`; treat it as you would any other user-supplied URL your server will
fetch.

### Configuring One Engine More Than Once

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

### Providers That Take a Choice of Credential

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

Option values for fields a provider declares as `secret` go through the same credential
resolver as `api_key`, so they accept `env://` and `credential://` references and are
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

Fields a provider declares as anything *other* than `secret` are passed through verbatim,
since resolving them would corrupt any literal value that merely looked like a reference.

To discover what a provider accepts without hardcoding it, read its setup spec; the
`any_of` groups are the ones where one of several fields will do:

```python
setup = ai.default_registry.get("anthropic").setup
[(f.key, f.required) for f in setup.fields]  # declared fields
setup.any_of  # (('api_key', 'oauth_token'),)
setup.requirement_note  # why, in one line
```

### Which Fields to Actually Ask For

Not every declared field is a question. A provider knows its own endpoint, its API
version, and where AWS keeps its credentials; what it cannot know is the developer's key
or account. The spec draws that line itself, so a setup form does not have to infer it from
help text:

```python
setup = ai.default_registry.get("openai").setup
[f.key for f in setup.essential_fields]  # ['api_key'] ; ask for these
[f.key for f in setup.advanced_fields]  # ['base_url']; offer these, folded away
```

An advanced field is never required and never part of an `any_of` group, so a form built
from `essential_fields` alone can always be saved. Each one carries its fallback in
`SetupField.default_value` (`https://api.openai.com/v1` here), which lets a collapsed
field still say what it will do. Render that value rather than pre-filling the editor
with it: a saved copy of today's default keeps overriding the real default after it has
moved on.

The two extremes: `ollama`, `vllm`, and the other local engines have no essential fields
at all, while `azure-foundry`, `runpod`, and anything else whose URL embeds an account or
endpoint id keeps `base_url` essential, because no default could be right.

## Client Settings

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
telemetry omits.

## Per-Request Options

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

## Environment Variables

| Variable | Effect |
|---|---|
| `ANYINFER_MODEL_DIR` | Override where downloaded models are stored (also `Client(model_dir=...)`). |
| `ANYINFER_RUNTIME_DIR` | Override where llama.cpp runtime variants are installed. |
| `ANYINFER_HARDWARE_CACHE_BYPASS` | Skip the hardware cache entirely, read and write. |
| `ANYINFER_HARDWARE_CACHE_REFRESH` | Ignore a cached profile, re-probe, and rewrite it. |
| `ANYINFER_SERVE_TOKEN` | Bearer token for `anyinfer serve`. |
| `COPILOT_CLI_PATH` | Override Copilot CLI discovery. |

Credential references (`env://NAME`) read any variable the reference names; there are no
magic credential variable names.

## Generating a File

`anyinfer init` writes a valid configuration from what the machine can already do
(running loopback engines and credential variables that are actually set), plus a runnable
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
configuration the loader accepts. Two consequences follow:

- An opt-in policy left entirely at its defaults still writes its block, as `{}`. The
  block's *presence* is what asks for the policy; dropping it would turn "pace this
  provider by whatever it reports" back into "do not pace it at all".
- `comments=True` writes a `_comment` string at the root rather than `//` lines. The
  format is JSON, so a generated file explains itself in something the loader accepts;
  reading it back changes nothing.

The writer emits credential settings exactly as they were given and never resolves a
reference. An `env://` or `credential://` value therefore stays safe to store, while a
literal credential stays literal. Review configurations constructed programmatically with
literal secrets before writing or committing them; `anyinfer init` itself writes references.

## File Format

Each provider entry needs an `id`. The other top-level provider settings are `adapter`,
`base_url`, `api_key`, `api_version`, `headers`, `timeout_s`, and `options`. Setup fields
declared by that provider may also be written directly, or grouped under a `values`
object (the shape setup UIs write); unrecognized fields fail validation. Two more keys
exist for compatibility: `provider_id` is the legacy spelling of `adapter`, and `alias`,
when present, must simply restate the entry's `id`. Credential references such as
`env://ANTHROPIC_API_KEY` are resolved only when the adapter is first used, so parsing a
config never prints or expands a secret.

### The `adapter` Key

`id` is the instance id used in target strings. The optional `adapter` key names the
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

The sidecar can advertise instance-scoped targets from `/v1/models` by writing them in
instance terms:

```bash
anyinfer serve --config anyinfer.json --expose work-azure:gpt-4o
```

### Provider `limits`

Request pacing is configured per provider instance because two accounts at the same
provider have independent allowances:

```json
{
  "providers": [
    {
      "id": "openai",
      "limits": {
        "max_concurrent": 4,
        "requests_per_minute": 120,
        "min_interval_s": 0.1,
        "respect_headers": true,
        "reserve_fraction": 0.1
      }
    }
  ]
}
```

Omitting `limits` disables pacing. An empty object opts into provider-reported rate-limit
headers without imposing a local fixed limit. Values are validated by `RateLimits`; unknown
keys and nonpositive or out-of-range values fail during configuration loading. How pacing
behaves at run time is covered in
[pacing before the limit](../concepts/routing.md#pacing-before-the-limit).

### The `context` Block

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

The block is optional, and every field defaults to the behavior AnyInfer has always had;
a file without it reduces exactly as before. The values above are what
`ContextTuning.recommended()` sets, which `anyinfer context --preset recommended` applies
without a file.

Read it back with `config.context` and pass it straight through:

```python
config = ai.load_config("anyinfer.json")
reduction = context.select(docs, query, max_tokens=8_000, tuning=config.context)
```

A misspelled setting is a `ConfigError`, not a silent no-op; a tuning key that silently
does nothing is worse than one that fails loudly. The sidecar reads the same file so one
config serves every frontend, but it does not reduce context itself: it is a wire codec
over a normal client, and reduction is the application's call about its own material.
What the sidecar *does* supply is this block as the default tuning for a wire context
request that omits its own `tuning`, so a gateway caller inherits the operator's settings
instead of silently falling back to the library defaults.

The full field list is on [`ContextTuning`](api/context.md#advanced-settings).

### The `history` Block

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

### The `cache` Block

Prompt-cache placement is opt-in because it changes provider billing and retention:

```json
{
  "cache": {
    "mode": "auto",
    "min_segment_tokens": 1024,
    "max_marks": 4,
    "include_tools": true,
    "include_system": true
  }
}
```

Omitting the block disables placement. An empty object enables the default `CachePolicy`;
`auto` chooses the strongest mechanism the resolved target offers. See
[prompt caching](../concepts/caching.md) for the mechanism and billing semantics.

### The `repair` Block

Bounded schema repair, opt-in because a repair round-trip costs another provider call:

```json
{
  "repair": {
    "max_attempts": 1
  }
}
```

Omitting the block means no repair: a response that violates the schema is surfaced as a
`SchemaViolationError` rather than retried. An empty object enables the default `Repair`.

This block is how a **sidecar deployment** reaches the repair loop at all. The Python API
takes `repair=` per call and the CLI has `run --repair`, but `anyinfer serve` builds its
client from this file — without the block, structured output through the sidecar validates
and 422s where the Python path would have recovered. See
[structured output](../concepts/structured-output.md#repair).

### The `observers` Block

Telemetry sinks the file can name. This is the only way a **sidecar deployment** gets an
access log: `anyinfer serve` has no constructor for a caller to reach, so a sink it cannot
name is a sink it cannot have.

```json
{
  "observers": [
    "logging",
    {"name": "jsonl", "options": {"path": "/var/log/anyinfer/telemetry.jsonl"}}
  ]
}
```

`logging` and `jsonl` ship with the library. Any other name is resolved through the
`anyinfer.observers` entry-point group, so a package can publish its own sink and have it
named here — an unknown name is a `ConfigError` at load, not a surprise at the first event.

Sinks are **described, not built**, exactly as [`mcp`](#the-mcp-block) servers are: loading
a configuration file never opens a log file. `anyinfer.config.build_observers` constructs
them when a frontend decides to observe. Both built-ins are content-free unless the
subscription opts into payloads, and every string they emit is redacted — see
[telemetry](api/telemetry.md#ready-made-sinks).

### The `operation_routes` Block

Embedding and reranking calls get their own default routes, so a client configured for
chat fallback never accidentally embeds with it:

```json
{
  "default_route": ["anthropic:claude-sonnet-4-5", "ollama:qwen3:8b"],
  "operation_routes": {
    "embedding": ["cohere:embed-v4.0", "ollama:nomic-embed-text"],
    "rerank": ["cohere:rerank-v3.5"]
  }
}
```

Valid keys are `embedding` and `rerank`; the generation default belongs in
`default_route`, and the loader rejects a `generation` key here so the two can never be
confused. `embed()` and `rerank()` use the matching entry when the caller names no
target; an explicit `target=` or `route=` argument always wins. With no entry configured,
they fall through to `default_route`, whose targets must actually declare the operation
or the call is refused before dispatch.

Note that an embedding fallback chain is still held to the embedding-space safety rule:
targets that are not the identical `provider:model` are refused unless the caller opts
in; see [Embeddings and reranking](../concepts/embeddings.md).

### The `arena` and `arenas` Blocks

[Arena](../concepts/arena.md) policies fan one request out to fixed targets and select
only after the candidates finish. A default policy and named policies use the same
complete field set:

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

### The `mcp` Block

MCP entries are inert server descriptions. Loading the file never starts a subprocess or
opens a connection:

```json
{
  "mcp": [
    {
      "name": "files",
      "command": ["mcp-server-filesystem", "./docs"],
      "env": {"MCP_TOKEN": "env://MCP_TOKEN"},
      "deny_tools": ["write_file"]
    },
    {
      "name": "search",
      "url": "https://tools.example.invalid/mcp",
      "headers": {"authorization": "env://SEARCH_MCP_TOKEN"},
      "timeout_s": 15,
      "allow_tools": ["search"]
    }
  ]
}
```

Every entry needs a unique `name` and exactly one of `command` or `url`. `command`,
`allow_tools`, and `deny_tools` are string lists; `env` and `headers` map non-empty strings
to strings; and `timeout_s` must be positive. Credential references in both `env` and
`headers` resolve only when `MCPToolset.connect()` is called and are registered for
redaction. See [the tool-loop guide](../guides/tool-loop.md#tools-from-an-mcp-server)
for discovery, trust boundaries, and the intentionally unsupported MCP surfaces.

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

A non-loopback bind requires both `--allow-remote-exposure` and a token. The CLI refuses
otherwise, since an unauthenticated gateway would let anyone on the network spend the
configured provider credentials.

## Cache and Data Locations

| Purpose | Windows | macOS | Linux |
|---|---|---|---|
| Hardware cache | `%LOCALAPPDATA%\anyinfer` | `~/Library/Caches/anyinfer` | `$XDG_CACHE_HOME/anyinfer` |
| Model artifacts | `%LOCALAPPDATA%\anyinfer\models` | `~/Library/Application Support/anyinfer/models` | `$XDG_DATA_HOME/anyinfer/models` |

Override the model directory with `options={"model_dir": Path(...)}` on the `llama-cpp`
provider.
