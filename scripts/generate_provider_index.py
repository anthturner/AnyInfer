"""Generate `docs/providers/all.md` — the complete provider index — from the registry.

The registry is the only place that knows what ships. A hand-written list of a hundred
providers is a list that is wrong within a release, so this renders one instead, and
`tests/test_docs_examples.py` fails if the checked-in page drifts from what this would
produce. Run it after adding or renaming a provider:

    python scripts/generate_provider_index.py

The page it writes is checked in rather than built at docs time, so the repository and
GitHub Pages agree and a reader browsing the source sees the same list as the site.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from anyinfer.providers.presets import COMPAT_PRESETS  # noqa: E402
from anyinfer.registry import ProviderRegistry  # noqa: E402

# Dedicated adapters get their own guide page; presets are documented as a group.
ADAPTER_PAGES = {
    "openai": "openai.md",
    "anthropic": "anthropic.md",
    "gemini": "gemini.md",
    "deepseek": "deepseek.md",
    "xai": "xai.md",
    "vertex": "vertex.md",
    "bedrock": "bedrock.md",
    "cohere": "cohere.md",
    "lm-studio": "lm-studio.md",
    "azure-foundry": "azure-foundry.md",
    "copilot": "copilot.md",
    "m365-copilot": "m365-copilot.md",
    "openrouter": "openrouter.md",
    "ollama": "ollama.md",
    "llama-cpp": "llama-cpp.md",
    "openai-compat": "openai-compat.md",
    "nebius": "nebius.md",
}

PRESETS_BY_ID = {p.id: p for p in COMPAT_PRESETS}

HEADER = """---
icon: material/format-list-bulleted
---

# Every provider

This is AnyInfer's compatibility inventory, not its primary value proposition:
**{total} providers** comprising {adapters} dedicated adapters with provider-specific
behavior and {presets} presets over the shared OpenAI-compatible adapter. Each is a
first-class target prefix: `groq:`, `vllm:`, `bedrock:`.

!!! note "This page is generated"

    It is rendered from the provider registry by
    `scripts/generate_provider_index.py` and verified by a test, so it cannot drift
    from what the library actually ships. Counts and columns come from the code.

```python
import anyinfer as ai

# Any row below works the same way — pick the id from the "Target" column.
client = ai.Client([ai.ProviderSettings.of("groq", api_key="env://GROQ_API_KEY")])
result = client.generate(prompt, target="groq:llama-3.3-70b-versatile")
```

New to these? Start with [choosing a provider](README.md); the per-provider quirks for
the preset table are in [hosted & local presets](presets.md).

## Dedicated adapters

These need more than declarative endpoint and auth settings: a native request shape,
special auth flow, richer discovery, or provider-specific stream handling. Each has its
own adapter and guide.

| Provider | Target | Kind | What it adds |
|---|---|---|---|
"""

PRESET_INTRO = """
## Presets

These speak the OpenAI chat-completions dialect closely enough that one shared adapter
covers them; what differs is declarative — endpoint, auth spelling, token-field name,
model listing, reasoning translation. See [presets](presets.md) for the quirk notes.

### Hosted services

| Provider | Target | Key (conventional env var) | Notes |
|---|---|---|---|
"""

LOCAL_INTRO = """
### Local engines & self-hosted servers

Local engines need no API key and default to loopback. Where the address is yours — a
cluster host, a dynamically assigned port — the preset requires a base URL instead.

| Provider | Target | Default endpoint | Notes |
|---|---|---|---|
"""

FOOTER = """
## Not yet covered

- **Replicate** — its predictions API is asynchronous and per-model, with no
  chat-completions route to normalize; `api.replicate.com/openapi.json` declares 26
  paths and none of them is one. A dedicated async adapter remains the only option.
- **Writer (Palmyra)** — serves `POST /v1/chat`, not `/chat/completions`, so no OpenAI
  client can reach it. The best candidate for the next dedicated adapter.

Anything else with an OpenAI-compatible endpoint already works today without waiting for
a preset — point the [generic adapter](openai-compat.md) at it:

```python
ai.ProviderSettings.of("openai-compat", base_url="https://your-host/v1", api_key="…")
```
"""


def _targets(provider_id: str, aliases: tuple[str, ...]) -> str:
    """Render the id and its aliases as code-formatted target prefixes."""
    return " / ".join(f"`{name}:`" for name in (provider_id, *aliases))


def _first_sentence(note: str) -> str:
    """Trim a preset note to its first sentence, for a table cell."""
    if not note:
        return ""
    sentence = note.split(". ")[0].rstrip(".")
    # Table cells cannot contain a raw pipe, and long notes belong on presets.md.
    return sentence.replace("|", "\\|")


def render() -> str:
    """Render the provider index from built-in registry descriptors."""
    registry = ProviderRegistry(load_builtins=True, load_entry_points=False)
    descriptors = [registry.get(pid) for pid in sorted(registry.known_ids())]
    adapters = [d for d in descriptors if d.id not in PRESETS_BY_ID]
    presets = [PRESETS_BY_ID[d.id] for d in descriptors if d.id in PRESETS_BY_ID]

    adapter_ids = {descriptor.id for descriptor in adapters}
    page_ids = set(ADAPTER_PAGES)
    if adapter_ids != page_ids:
        missing = sorted(adapter_ids - page_ids)
        stale = sorted(page_ids - adapter_ids)
        raise RuntimeError(f"provider guide mapping mismatch: missing={missing}, stale={stale}")
    if len(set(ADAPTER_PAGES.values())) != len(ADAPTER_PAGES):
        raise RuntimeError("every dedicated adapter must have its own provider guide")
    for page in ADAPTER_PAGES.values():
        if not (REPO_ROOT / "docs" / "providers" / page).is_file():
            raise RuntimeError(f"provider guide does not exist: docs/providers/{page}")

    out = [HEADER.format(total=len(descriptors), adapters=len(adapters), presets=len(presets))]

    for descriptor in adapters:
        page = ADAPTER_PAGES[descriptor.id]
        name = f"[{descriptor.display_name}]({page})"
        kind = "Local" if descriptor.locality == "local" else "Hosted"
        summary = ADAPTER_SUMMARIES.get(descriptor.id, "")
        out.append(
            f"| {name} | {_targets(descriptor.id, descriptor.aliases)} | {kind} | {summary} |\n"
        )

    out.append(PRESET_INTRO)
    for preset in (p for p in presets if p.locality == "hosted"):
        key = f"`{preset.key_env}`" if preset.key_env else "—"
        out.append(
            f"| {preset.display_name} | {_targets(preset.id, preset.aliases)} | {key} "
            f"| {_first_sentence(preset.note)} |\n"
        )

    out.append(LOCAL_INTRO)
    for preset in (p for p in presets if p.locality == "local"):
        endpoint = f"`{preset.base_url}`" if preset.base_url else "_you supply it_"
        out.append(
            f"| {preset.display_name} | {_targets(preset.id, preset.aliases)} "
            f"| {endpoint} | {_first_sentence(preset.note)} |\n"
        )

    out.append(FOOTER)
    return "".join(out)


ADAPTER_SUMMARIES = {
    "openai": "Responses API, reasoning-token accounting",
    "anthropic": "Messages API, extended thinking deltas; any Anthropic-shaped endpoint",
    "gemini": "Native `generateContent`, thinking levels, discovered windows",
    "deepseek": "Separate reasoning channel, split cache accounting",
    "xai": "Provider-reported cost, discovered pricing",
    "vertex": "Gemini with GCP auth; project-scoped addressing",
    "bedrock": "Converse API, SigV4 or API key, binary event-stream framing",
    "cohere": "Native v2 chat, grounded generation, thinking channel",
    "lm-studio": "Native discovery: context, quantization, residency",
    "azure-foundry": "Deployment-addressed, `api-version` pinning",
    "copilot": "GitHub Copilot subscription; auth delegated to the Copilot CLI",
    "m365-copilot": "Microsoft 365 Copilot Chat, Entra auth",
    "openrouter": "Router across upstreams, discovered per-model pricing",
    "ollama": "Native API, grammar schemas, phase timings",
    "llama-cpp": "Supervised `llama-server`, loopback only",
    "openai-compat": "Any `/chat/completions` endpoint by URL",
    "nebius": "Verbose listing: discovered pricing, context and quantization",
}


def main() -> int:
    """Rewrite the generated index and return a process exit code."""
    target = REPO_ROOT / "docs" / "providers" / "all.md"
    rendered = render()
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        print(f"{target.relative_to(REPO_ROOT)} already current")
        return 0
    target.write_text(rendered, encoding="utf-8")
    print(f"wrote {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
