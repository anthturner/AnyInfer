# Writing a provider adapter

An adapter translates. That is the whole job, and keeping it that way is what lets one
conformance suite cover every provider.

## The contract

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

`WireRequest` arrives **fully resolved** — concrete model, chosen mechanism, projected
schema, translated reasoning effort, merged options. You never see aliases, routing policy,
or repair state.

You may emit only: `TextDelta`, `ReasoningDelta`, `ToolCallDelta`, `UsageUpdate`, and
exactly one terminal `AdapterFinal`.

## What you must not do

- Retry. The router does that, and doing both multiplies the attempts.
- Validate schemas or repair responses. The core does.
- Measure TTFT or duration. The core does, identically for everyone.
- Consult routing policy or the catalog.

`lint-imports` enforces this. If it fails, move the code.

## Start from a descriptor

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
you can add a declarative field here.

Three fields worth understanding:

- **`SetupField.advanced`**: set it on every field you already have a working value for,
  and put that value in `default_value`. It is what keeps a config UI down to the
  questions only the user can answer: mark the endpoint you default to, the version you
  pin, and the credential path that only a non-standard deployment uses. A required field
  may not be advanced — hiding something that blocks saving is the failure this prevents —
  and `ProviderSetupSpec` rejects that combination at import time.
- **`grammar_needs_prompt_injection`**: set it when your engine compiles a schema to a
  decoding grammar *without* conditioning the model on it. A grammar guarantees well-formed
  JSON, not meaningful JSON.
- **`ignored_parameters`**: declare anything your provider accepts and silently discards.
  The core emits `ParameterDropped` so users find out.

## If it speaks OpenAI

Subclass and override only what differs:

```python
class MyAdapter(OpenAICompatAdapter):
    provider_id: ClassVar[str] = "my-provider"
    output_tokens_field: ClassVar[str] = "max_completion_tokens"

    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        headers = super()._build_headers(config)
        headers["x-my-header"] = "value"
        return headers
```

`azure_foundry.py` and `openrouter.py` are both small for exactly this reason — read them
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

## Register it

Built-ins go in `providers/__init__.py`. Third-party adapters advertise themselves:

```toml
[project.entry-points."anyinfer.providers"]
my_provider = "my_package.adapter:descriptor"
```

Discovery is lazy and collision-safe. A plugin that fails to import is skipped rather than
breaking every other provider.

## Certify it

```python
from anyinfer.testing.conformance import Capabilities, ConformanceHarness, run_conformance


async def build_client(scenario: str) -> AsyncClient:
    return AsyncClient(
        [ProviderSettings.of("my-provider", transport=fake_for(scenario).transport())]
    )


HARNESS = ConformanceHarness(
    provider_id="my-provider",
    model="my-model",
    build_client=build_client,
    supports=Capabilities(reasoning=False),  # declare what you genuinely cannot do
)

results = await run_conformance(HARNESS)
assert all(r.passed or r.skipped for r in results)
```

Declare unsupported behaviors explicitly in `Capabilities`. A declared ➖ is a documented
limitation; a silently passing test is a lie that will cost a user an afternoon.

See [the conformance suite](conformance.md).

## Ship it with

- the adapter;
- a contract snapshot in `contracts/`;
- a conformance harness;
- a provider page in `docs/providers/`;
- a row in the [matrix](../reference/conformance-matrix.md), regenerated, not hand-edited.
