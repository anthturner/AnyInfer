# Quickstart

From `pip install` to a working result. Every example on this page is executed in CI against
the fake providers, so none of it can quietly rot.

## Install

```bash
pip install anyinfer
```

The core depends on `httpx2` and `jsonschema` and nothing else. Providers that need more come
as extras — see [installation](installation.md).

## Zero to a working call

`anyinfer init` inspects the machine, reports what is already usable, and writes a valid
configuration plus a runnable starter program:

```bash
anyinfer init
python starter.py
```

```text
detected   Linux / x86_64, 32.0 GiB RAM, NVIDIA RTX 4070 (12.0 GiB)
probed     17 loopback endpoint(s), every one a provider default:
           http://127.0.0.1:11434, http://127.0.0.1:1234/v1, …
found      ollama at http://127.0.0.1:11434 (4 models)
found      anthropic, credential env://ANTHROPIC_API_KEY
recommend  medium -> ollama:qwen3:8b

wrote      anyinfer.json
wrote      starter.py
```

What it will and will not do:

- **It only reports what it observed.** A provider is written into the file because a
  loopback endpoint it declares answered, or because a credential variable it names is set —
  never because it might work.
- **It never writes a credential value.** A detected key becomes `"api_key":
  "env://ANTHROPIC_API_KEY"`, the reference and not the secret, so the generated file is safe
  to commit.
- **It never installs anything.** Use [`anyinfer models add`](../guides/local-models.md) to
  download weights and `anyinfer runtime install` for a llama.cpp runtime.
- **It never replaces a file you already have.** An existing `anyinfer.json` stops the
  command; pass `--force` to replace it or `--output` to write elsewhere.

Useful flags: `--no-probe` contacts nothing at all, `--keyring` also looks in the OS
credential vault, and `--json` emits the same findings for a script.

The file it writes is the [shared configuration](../reference/configuration.md) format —
the same file the command-line runner, the sidecar, and the Python API all read.

## Your first call

=== "Sync"

    ```python hl_lines="8"
    import anyinfer as ai

    client = ai.Client(
        [
            ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
        ]
    )

    result = client.generate(
        "Summarize this in one sentence:\n" + text,
        target="anthropic:claude-sonnet-4-5",
    )

    print(result.text)
    client.close()
    ```

=== "Async"

    ```python hl_lines="9"
    import anyinfer as ai

    async with ai.AsyncClient(
        [
            ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
        ]
    ) as client:
        result = await client.generate(
            "Summarize this in one sentence:\n" + text,
            target="anthropic:claude-sonnet-4-5",
        )

        print(result.text)
    ```

The highlighted line is the only one that changes when you point the same call at a
different provider or a local model.

Note the credential: `"env://ANTHROPIC_API_KEY"` is a *reference*, safe to keep in a config
file. It is resolved once and registered for redaction, so the key can never appear in a log
line or an error message. See [credentials](../concepts/credentials.md).

`Client` owns a background event loop, so use it as a context manager or call `close()`:

```python
with ai.Client([ai.ProviderSettings.of("ollama")]) as client:
    result = client.generate("Why is the sky blue?", target="ollama:qwen3:8b")
```

## Streaming

```python
with client.stream(messages, target="ollama:qwen3:8b") as stream:
    for event in stream:
        if isinstance(event, ai.TextDelta):
            print(event.text, end="", flush=True)

    final = stream.result
    print(f"\n\n{final.usage.output_tokens} tokens in {final.timing.total_ms:.0f} ms")
```

Using the stream as a context manager matters: leaving the block early cancels the in-flight
request instead of letting it run on.

## Aliases: don't hardcode model names

`small`, `medium`, and `large` resolve to a concrete model for whichever provider you have
configured:

```python
client = ai.Client(
    [
        ai.ProviderSettings.of("ollama"),
        ai.ProviderSettings.of("anthropic", api_key="env://ANTHROPIC_API_KEY"),
    ]
)

result = client.generate(prompt, target="medium")  # -> ollama, since it is listed first
```

The order you configure providers is the preference order. See
[targets and aliases](../concepts/targets.md).

## Structured output

Pass a JSON schema and get back a validated Python value:

```python
SUMMARY = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "topics"],
}

result = client.generate(
    article,
    target="medium",
    schema=SUMMARY,
    repair=ai.Repair(max_attempts=1),
)

print(result.structured["headline"])
print(result.structured_mechanism)  # "json_schema", "grammar", "json_mode", or "prompt"
```

AnyInfer uses the strongest mechanism the provider supports, then validates the result
against *your* schema regardless. `repair` lets the model correct itself once if it gets the
shape wrong. See [structured output](../concepts/structured-output.md).

## Fallback chains

```python
route = ai.Route(
    targets=("anthropic:claude-sonnet-4-5", "openai:gpt-5", "ollama:qwen3:8b"),
    retry=ai.Retry(max_attempts=3),
)

result = client.generate(prompt, route=route)

print(f"served by {result.target}")
for attempt in result.attempts:
    print(f"  {attempt.target} -> {attempt.outcome}")
```

Every result carries its full routing trail, so "why was this slow?" is answerable after the
fact. See [routing](../concepts/routing.md).

## Async

`Client` is a facade; `AsyncClient` is the real implementation and has the same surface:

```python
async with ai.AsyncClient(
    [ai.ProviderSettings.of("openai", api_key="env://OPENAI_API_KEY")]
) as client:
    result = await client.generate(prompt, target="openai:gpt-5")

    async with client.stream(prompt, target="openai:gpt-5") as stream:
        async for event in stream:
            ...
```

## Running a local model

```python
from anyinfer import local

profile = local.detect()  # cached hardware probe
recommendation = local.recommend_alias(profile, ai.load_default_catalog())

print(recommendation.alias, "-", recommendation.reason)
```

With `llama-cpp` configured, generating against that alias downloads the pinned GGUF,
verifies its hash, tunes a server for your hardware, starts it on loopback, and answers —
all from one `generate()` call. See [local inference](local-inference.md).

## What next

- [Concepts](../concepts/README.md): the model behind the API.
- [Choosing an integration path](integration-paths.md): SDK or standalone service?
- [Providers](../providers/README.md): the quirks of each backend.
