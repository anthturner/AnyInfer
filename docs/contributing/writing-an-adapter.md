# Writing a Provider Adapter

An [adapter](../reference/glossary.md#adapter) translates. That is the whole job, and
keeping it that way is what lets one conformance suite cover every provider. This page
explains the shape and the reasoning behind it.

For the step-by-step procedure (what to research before writing code, which registration
gates a new provider trips, and what "done" means), follow
[`contracts/NEW-PROVIDER.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/NEW-PROVIDER.md).
It is the canonical checklist that this repository's coding-agent skills run, and it starts
where every provider should: fetching the current API reference and recording what it says,
before any code exists to be biased by.

## The Contract

Four methods:

```python
class MyAdapter:
    provider_id: ClassVar[str] = "my-provider"

    def __init__(self, config: ProviderConfig) -> None: ...

    async def list_models(self) -> Sequence[DiscoveredModel]: ...
    async def health(self) -> Health: ...
    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]: ...
    async def aclose(self) -> None: ...
```

`WireRequest` arrives fully resolved: concrete model, chosen mechanism, projected
schema, translated reasoning effort, merged options. You never see aliases, routing policy,
or repair state.

You may emit only: `TextDelta`, `ReasoningDelta`, `ToolCallDelta`, `UsageUpdate`, and
exactly one terminal `AdapterFinal`.

## What You Must Not Do

- Retry. The router does that, and doing both multiplies the attempts.
- Validate schemas or repair responses. The core does.
- Measure TTFT or duration. The core does, identically for everyone.
- Consult routing policy or the catalog.

`lint-imports` enforces this. If it fails, move the code.

## Start from a Descriptor

```python
descriptor = ProviderDescriptor(
    id="my-provider",
    display_name="My Provider",
    aliases=("mine",),
    factory=MyAdapter,
    locality="hosted",
    default_base_url="https://api.example.com/v1",
    requires_base_url=False,
    setup=ProviderSetupSpec(
        fields=(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=True,
                help_text="Accepts env:// and credential:// references.",
            ),
            SetupField(
                key="base_url",
                label="Base URL",
                kind="endpoint",
                advanced=True,
                default_value="https://api.example.com/v1",
                help_text="Defaults to https://api.example.com/v1.",
            ),
        ),
    ),
    reasoning_translator=lambda effort: {} if effort is None else {"effort": effort},
    default_capabilities=ModelCapabilities(
        features=Sourced(Feature.STREAMING | Feature.TOOLS, "default")
    ),
)
```

`setup` is what lets config UIs stay generic; never add a per-engine branch to UI code when
you can add a declarative field here. Full signatures for `ProviderDescriptor`,
`ProviderSetupSpec`, and `SetupField` are in
[the registry API](../reference/api/registry.md), and how `advanced` and `default_value`
drive a setup form is covered in
[shared configuration](../reference/configuration.md#which-fields-to-actually-ask-for).

Two fields worth understanding:

- `grammar_needs_prompt_injection`: set it when your engine compiles a schema to a
  decoding grammar *without* conditioning the model on it. A grammar guarantees well-formed
  JSON, not meaningful JSON.
- `ignored_parameters`: declare anything your provider accepts and silently discards.
  The core emits `ParameterDropped` so users find out.

## If It Speaks OpenAI

Subclass [the OpenAI-compatible adapter](../providers/openai-compat.md) and override only
what differs:

```python
class MyAdapter(OpenAICompatAdapter):
    provider_id: ClassVar[str] = "my-provider"
    output_tokens_field: ClassVar[str] = "max_completion_tokens"

    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        headers = super()._build_headers(config)
        headers["x-my-header"] = "value"
        return headers
```

`azure_foundry.py` and `openrouter.py` are both small for exactly this reason; read them
before writing a new dialect from scratch.

## Errors

Raise only `ProviderError` subclasses, with `retryable` and `retry_after_s` set. Use the
shared helpers so classification is consistent:

```python
from .http import classify_status, map_transport_error, read_error_detail

raise classify_status(
    response.status_code,
    provider=self.provider_id,
    detail=read_error_detail(body),
    headers=response.headers,
)
```

Every error deserves an actionable `hint`. "Invalid request" is not a hint; "verify the
model id, or list available models with client.models()" is.

## Register It

Built-ins go in `providers/__init__.py`. Third-party adapters advertise themselves:

```toml
[project.entry-points."anyinfer.providers"]
my_provider = "my_package.adapter:descriptor"
```

Discovery is lazy and collision-safe. A plugin that fails to import is skipped rather than
breaking every other provider.

## Certify It

Run [the conformance suite](conformance.md) against your adapter through a
`ConformanceHarness`, declaring anything the provider cannot do in `Capabilities` so the
matrix records a ➖ instead of overstating support. The harness, the run modes, and
cassette recording are all covered there.
