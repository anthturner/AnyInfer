---
provider: azure-foundry
icon: material/domain
---

# Azure AI Foundry

An [`openai-compat`](openai-compat.md) subclass carrying Azure's parameter renames and
its two authentication modes.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: health</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: discovery</span>
</div>

## Setup

=== "API key"

    ```python
    client = ai.Client(
        [
            ai.ProviderSettings.of(
                "azure-foundry",
                base_url="https://<resource>.services.ai.azure.com/openai/v1",
                api_key="env://AZURE_AI_KEY",
            ),
        ]
    )
    result = client.generate(prompt, target="azure-foundry:gpt-5")
    ```

=== "Entra"

    ```bash
    pip install "anyinfer[azure]"
    az login
    ```

    ```python
    ai.ProviderSettings.of(
        "azure-foundry",
        base_url="https://<resource>.services.ai.azure.com/openai/v1",
        # no api_key: DefaultAzureCredential is used
    )
    ```

Aliases: `azure`, `foundry`.

## Differences from openai-compat

| | Azure |
|---|---|
| Output-token parameter | `max_completion_tokens` |
| Reasoning effort | flat `reasoning_effort` field |
| Auth header | `api-key`, or `Authorization: Bearer` for Entra |
| API version | optional `api-version` query parameter |

Sending `max_tokens` to Azure is rejected outright, which is why the subclass exists.

## API Versions

```python
ai.ProviderSettings.of("azure-foundry", base_url=..., api_version="2024-10-21")
```

Only needed for deployments that still require it; the newer `/openai/v1` surface does not.
Chat, embeddings, and model listing all carry it consistently.

## Embeddings

```python
result = client.embed(
    ["first text", "second text"],
    target="azure-foundry:text-embedding-3-small",
)
```

`target`'s model half is the deployment name, not necessarily the underlying model's
catalog id. The same `POST {base_url}/embeddings` surface as chat (deployment-less on
`/openai/v1`, or `api-version`-pinned on the older surface) speaks the identical
OpenAI-compatible body.

Azure documents the same request ceilings [OpenAI itself does](openai.md#embeddings):
2,048 inputs per request, 8,192 tokens per input, and 300,000 tokens aggregate. Since the
deployment name is tenant-chosen, AnyInfer does not declare these as static per-model
[capabilities](../concepts/capabilities.md); a request larger than what the deployment
accepts surfaces as a provider error rather than a pre-flight refusal.

## Troubleshooting

**`could not acquire an Entra token`**: run `az login`, or configure a service principal in
the environment. The error names the scope it tried.

**`azure-foundry requires the base URL of your Foundry resource`**: the resource endpoint
is deployment-specific and cannot be defaulted.

## Wire Contract

For the exact request/response fields this adapter depends on, see
[contracts/azure-foundry.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/azure-foundry.md).

## See Also

<div class="anyinfer-see-also" markdown>

- [Credentials](../concepts/credentials.md): Entra tokens versus a plain API key.
- [Targets and aliases](../concepts/targets.md): addressing one deployment among several.

</div>
