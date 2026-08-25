---
provider: vertex
icon: material/google-cloud
---

# Google Vertex AI

The same Gemini models as [the AI Studio API](gemini.md), over the same protocol, with
enterprise addressing and Google Cloud authentication. AnyInfer reuses the Gemini
adapter's translation wholesale — Vertex changes *where* requests go and *how* they are
signed, not what they look like.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: reasoning</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: discovery (no listing endpoint)</span>
</div>

## Setup

```python
import anyinfer as ai

client = ai.Client(
    [
        ai.ProviderSettings.of(
            "vertex",
            options={"project": "my-gcp-project", "location": "global"},
        ),
    ]
)

result = client.generate(prompt, target="vertex:gemini-2.5-flash")
```

`project` is required — it is part of the request path, not a header. `location` defaults
to `global`; newer models are served **only** from the global endpoint, while a regional
value (`us-central1`) selects that region's host.

`vertex-ai:` and `google-vertex:` are accepted aliases.

## Authentication

Vertex takes an OAuth access token, not an API key, so the credential is acquired and
refreshed instead of configured once. Three ways, in precedence order:

=== "Application default credentials"

    Install `google-auth`, then let its standard credential chain select metadata-server,
    workload-identity, or local `gcloud` credentials:

    ```bash
    pip install google-auth
    ```

    ```python
    ai.ProviderSettings.of("vertex", options={"project": "my-project"})
    ```

    AnyInfer uses `google-auth` when it is installed. The library is optional because it is
    not needed for the explicit-token or service-account paths.

=== "A service-account key"

    ```bash
    pip install "anyinfer[vertex]"
    ```

    ```python
    ai.ProviderSettings.of(
        "vertex",
        options={
            "project": "my-project",
            "credentials_file": "/secrets/sa.json",
        },
    )
    ```

    Falls back to `GOOGLE_APPLICATION_CREDENTIALS`. The JWT is signed and exchanged
    in-house, so this works without `google-auth` — though signing needs an RSA
    implementation, and the error says so if none is available.

=== "A pre-acquired token"

    ```python
    ai.ProviderSettings.of(
        "vertex", api_key="env://GCP_ACCESS_TOKEN", options={"project": "my-project"}
    )
    ```

    From `gcloud auth print-access-token`. Used verbatim and **never refreshed** — its
    lifetime is yours to manage. Note this is an access token, not a Gemini API key; the
    two are not interchangeable.

Acquired tokens are cached until two minutes before expiry, so a long-running client pays
for one exchange per hour, not one per request.

## Everything else is Gemini

Thinking levels, response schemas, function calling, and usage accounting all behave
exactly as on [the Gemini page](gemini.md), including `output_tokens` counting answer
plus thinking:

```python
result = client.generate(prompt, target="vertex:gemini-2.5-pro", reasoning="high")
print(result.usage.reasoning_tokens)
```

## Discovery

Vertex exposes no listing endpoint comparable to AI Studio's, so
`client.models("vertex")` returns an empty list — under the
[provenance rules](../concepts/capabilities.md), an invented inventory must not be
presented as discovery. Name models explicitly in the target, and supply
`capability_overrides` if you want their windows known.

Health checks that a token can be acquired, without spending a generation.

## Embeddings

Embeddings do not reuse the Gemini shape: Vertex's own text-embeddings API uses a
`predict` verb with an `instances`/`parameters` body, so `VertexAdapter` overrides
embedding translation instead of Gemini's `batchEmbedContents`:

```python
result = client.embed(
    ["first text", "second text"],
    target="vertex:text-embedding-005",
)
```

`gemini-embedding-001` accepts only one input per request — a documented Vertex limit —
so [the core's batching policy](../concepts/embeddings.md#batching) fans a multi-text
call into one request per input. `text-embedding-005` and
`text-multilingual-embedding-002` accept up to five. `dimensions=` requests native
truncation via `outputDimensionality`; `input_type=` maps to Vertex's `task_type`
(`query`→`RETRIEVAL_QUERY`, `document`→`RETRIEVAL_DOCUMENT`,
`classification`→`CLASSIFICATION`, `clustering`→`CLUSTERING`).

## Claude on Vertex

Vertex also serves Anthropic models, but through a different surface
(`rawPredict`/`streamRawPredict` with the Messages body). This adapter does not cover it —
point the [Anthropic adapter](anthropic.md) at that endpoint instead.

## See also

<div class="anyinfer-see-also" markdown>

- [Contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/vertex.md)
- [Google Gemini](gemini.md): the same models with API-key auth.

</div>
