# Quickstart

From `pip install` to a working result. Every example on this page is executed in CI
against the fake providers, so none of it can quietly rot.

## Install

```bash
pip install anyinfer
```

The core depends on `httpx2` and `jsonschema` and nothing else. Providers that need more
come as extras — see [installation](installation.md).

The fastest start is `anyinfer init`: it inspects the machine, reports which providers
are already usable (a running Ollama, a set credential variable), and writes a valid
`anyinfer.json` plus a runnable `starter.py` — without ever storing a secret or
installing anything. The
[CLI guide](cli.md#getting-a-config-file-in-the-first-place) covers what it detects and
its flags. The file it writes is the
[shared configuration](../reference/configuration.md) the SDK, CLI, and sidecar all
read.

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

Note the credential: `"env://ANTHROPIC_API_KEY"` is a *reference*, safe to keep in a
config file. It is resolved once and registered for redaction, so the key can never
appear in a log line or an error message. See
[credentials](../concepts/credentials.md).

`Client` owns a background event loop, so use it as a context manager or call
`close()`:

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

Using the stream as a context manager matters: leaving the block early cancels the
in-flight request instead of letting it run on. See
[stream typed events](streaming.md).

## Aliases: don't hardcode model names

`small`, `medium`, and `large` resolve to a concrete model for whichever provider you
have configured:

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
against *your* schema regardless. `repair` lets the model correct itself once if it
gets the shape wrong. See [structured output](../concepts/structured-output.md).

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

Every result carries its full routing trail, so "why was this slow?" is answerable
after the fact. See [routing and rate limits](../concepts/routing.md).

## Beyond generation

The same client embeds and reranks (`client.embed()`, `client.rerank()`) — typed and
routed like generation, with a
[safety rule](../concepts/embeddings.md#the-embedding-space-safety-rule) that keeps
fallback from mixing incompatible vector spaces. And a local model is just another
target: with `llama-cpp` configured, one `generate()` call downloads a pinned,
hash-verified model, tunes a server for your hardware, and answers on loopback — see
[run a model locally](local-inference.md).

!!! tip "Key takeaways"
    - One call shape covers every provider; only the `target=` string changes.
    - Credentials are references (`env://…`), resolved once and redacted everywhere.
    - A schema is validated client-side no matter which mechanism the provider offers.
    - Every result carries its attempt trail, so routing decisions are inspectable
      after the fact.

## See also

<div class="anyinfer-see-also" markdown>

- [Concepts](../concepts/README.md): the model behind the API.
- [Integrate AnyInfer](README.md): SDK, CLI, or sidecar.
- [Providers](../providers/README.md): the quirks of each backend.

</div>
