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
    alias=None,                             # instance id; defaults to the provider id
    base_url="https://api.openai.com/v1",   # provider default when omitted
    api_key="env://OPENAI_API_KEY",         # literal, env://, or credential://
    api_version=None,                       # Azure and Anthropic
    headers={},                             # extra request headers
    options={},                             # adapter-specific settings
    timeout_s=120.0,                        # default per-request timeout
)
```

The **order** you list providers is the preference order for
[alias resolution](../concepts/targets.md#aliases).

### Configuring one engine more than once

`alias` gives an entry its own identity, so the same engine can be configured several
times — two Azure tenants, a local and a remote Ollama — each with its own endpoint and
credentials. The alias is what a target string names:

```python
client = ai.Client([
    ai.ProviderSettings.of("azure-foundry", alias="work",
                            base_url="https://work.openai.azure.com",
                            api_key="env://WORK_KEY"),
    ai.ProviderSettings.of("azure-foundry", alias="lab",
                            base_url="https://lab.openai.azure.com",
                            api_key="env://LAB_KEY"),
])

client.generate(messages, target="work:gpt-4o")   # the work tenant, not the lab one
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
# An Anthropic API key — sent as x-api-key.
ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY")

# A claude.ai OAuth token — sent as a bearer token, with the beta flag the API requires.
# Obtain one with: ant auth print-credentials --access-token
ai.ProviderSettings.of("anthropic", options={"oauth_token": "env://ANTHROPIC_OAUTH_TOKEN"})
```

Supply one or the other; if both are set the OAuth token wins.

**Option values for fields a provider declares as `secret` go through the same credential
resolver as `api_key`**, so they accept `env://` and `credential://` references and are
registered for redaction. Bedrock's explicit AWS credentials work the same way:

```python
ai.ProviderSettings.of("bedrock", options={
    "aws_access_key_id": "AKIA…",                        # an identifier, passed through
    "aws_secret_access_key": "env://AWS_SECRET_ACCESS_KEY",  # resolved and redacted
})
```

Fields a provider declares as anything *other* than `secret` are passed through verbatim —
resolving them would corrupt any literal value that merely looked like a reference.

To discover what a provider accepts without hardcoding it, read its setup spec — the
`any_of` groups are the ones where one of several fields will do:

```python
setup = ai.default_registry.get("anthropic").setup
[(f.key, f.required) for f in setup.fields]  # declared fields
setup.any_of                                 # (('api_key', 'oauth_token'),)
setup.requirement_note                       # why, in one line
```

## Client settings

```python
ai.Client(
    providers,
    registry=None,              # defaults to the process-wide registry
    catalog=None,               # defaults to the bundled catalog
    route=None,                 # default route when a call names no target
    observers=[],               # telemetry sinks, registered payload-free
    resolver=None,              # credential resolver chain
    retain_raw=False,           # keep raw provider payloads on results
    repair=None,                # default repair budget
    use_default_catalog=True,   # False disables alias resolution entirely
    estimator=None,             # token counting; defaults to the byte heuristic
    context_gate=True,          # refuse requests that provably cannot fit pre-dispatch
    pricing_table=None,         # defaults to the bundled table; see fetch_pricing()
    capability_overrides=None,  # "provider:model"-keyed corrections, strongest layer
    model_dir=None,             # where acquired model weights are stored
)
```

`retain_raw` is off by default because raw payloads carry response text that payload-free
telemetry deliberately omits.

## Per-request options

```python
client.generate(
    messages,
    target="medium",                # or route=
    schema=None,
    tools=(),
    tool_choice="auto",             # "auto" | "none" | "required" | a tool name
    sampling=ai.Sampling(...),
    reasoning=None,                 # "minimal" | "low" | "medium" | "high"
    timeout_s=None,                 # per attempt; defaults to 120
    repair=None,
    provider_options={},            # namespaced escape hatch
    metadata={},                    # opaque, echoed in telemetry
    max_response_bytes=1_048_576,
)
```

`Sampling` fields default to `None`, meaning *provider default*. AnyInfer never invents a
temperature — an unset value is omitted from the wire request entirely.

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

## File format

```json
{
  "format_version": 1,
  "providers": [
    {"id": "anthropic", "api_key": "env://ANTHROPIC_API_KEY"},
    {"id": "ollama"},
    {
      "id": "llama-cpp",
      "options": {"posture": "balanced", "binary": "/usr/local/bin/llama-server"}
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

The sidecar can advertise instance-scoped targets from `/v1/models` by writing them in
instance terms:

```bash
anyinfer serve --config anyinfer.json --expose work-azure:gpt-4o
```

## CLI

```bash
anyinfer serve --host 127.0.0.1 --port 8080 --config anyinfer.json
anyinfer serve --token SECRET --host 0.0.0.0 --allow-remote-exposure
anyinfer run "PROMPT" --config anyinfer.json   # one prompt, then exit
anyinfer doctor [--json]        # detected hardware, recommended tier
anyinfer providers [--json]     # every registered provider and what it needs
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
