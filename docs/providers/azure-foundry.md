---
provider: azure-foundry
icon: material/domain
---

# Azure AI Foundry

An `openai-compat` subclass carrying Azure's parameter renames and its two authentication
modes.

<div class="anyinfer-badge-row" markdown="span">
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: streaming</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: structured output</span>
<span class="anyinfer-badge anyinfer-badge-yes">:material-check: tool calls</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: health</span>
<span class="anyinfer-badge anyinfer-badge-partial">:material-minus: discovery</span>
</div>

## Setup with an API key

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

## Setup with Entra

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

## Differences from vanilla openai-compat

| | Azure |
|---|---|
| Output-token parameter | `max_completion_tokens` |
| Reasoning effort | flat `reasoning_effort` field |
| Auth header | `api-key`, or `Authorization: Bearer` for Entra |
| API version | optional `api-version` query parameter |

Sending `max_tokens` to Azure is rejected outright, which is why the subclass exists.

## API versions

```python
ai.ProviderSettings.of("azure-foundry", base_url=..., api_version="2024-10-21")
```

Only needed for deployments that still require it; the newer `/openai/v1` surface does not.
The parameter is applied per instance, so it cannot leak onto other adapters.

## Troubleshooting

**`could not acquire an Entra token`** — run `az login`, or configure a service principal in
the environment. The error names the scope it tried.

**`azure-foundry requires the base URL of your Foundry resource`** — the resource endpoint
is deployment-specific and cannot be defaulted.

## Wire contract

For the exact request/response fields this adapter depends on, see
[contracts/azure-foundry.md](https://github.com/anthturner/AnyInfer/blob/main/contracts/azure-foundry.md).
