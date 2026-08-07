# lm-studio — Protocol Contract

Status: **implemented** — `providers/lm_studio.py`, an `openai-compat` subclass with
native discovery.
Last verified: 2026-08-07 — against live LM Studio documentation (sources below).

## Upstream sources
- https://lmstudio.ai/docs/app/api/endpoints/openai
- https://lmstudio.ai/docs/app/api/endpoints/rest
- https://lmstudio.ai/docs/app/api
- https://lmstudio.ai/docs/developer/rest
- https://lmstudio.ai/docs/developer/rest/chat
- https://lmstudio.ai/docs/developer/rest/list
- https://lmstudio.ai/docs/developer/rest/endpoints
- https://lmstudio.ai/docs/developer/openai-compat
- https://lmstudio.ai/docs/developer/anthropic-compat
- https://lmstudio.ai/docs/developer/core/ttl-and-auto-evict

## Split surface

Generation uses LM Studio's **OpenAI-compatible** endpoint, so the chat dialect is
`contracts/openai-compat.md` unchanged. Discovery uses the **native REST API**, because
the compatibility layer reports ids alone while the native one reports what a local
engine's inventory actually means: context length, quantization, size, and which models
are *loaded*.

## Wire contract

### Endpoints
- `POST {base}/chat/completions` — generation, OpenAI-compatible. Default base
  `http://127.0.0.1:1234/v1`; a bare hostname expands to `http://<host>:1234`.
- `GET {server root}/api/v1/models` — native discovery. Sits **beside** `/v1`, not under
  it, so the adapter strips a trailing `/v1` from the base URL to reach it.

### Auth
- `Authorization: Bearer <token>`, only when LM Studio's authentication is enabled.
  Loopback by default and typically keyless.

### Version pins
- None. A 404 on `/api/v1/models` degrades to the OpenAI listing, so older builds without
  the native API still work.

### Request fields sent
- The openai-compat dialect unchanged.
- `reasoning`: `off`, `low`, `medium`, `high`, or `on` — normalized effort maps across,
  with `minimal` clamped to `low` rather than `off`, since disabling reasoning is a
  behavior change rather than a reduction.

### Response fields read (native discovery)
- `models[]` — `key` (the model id), `type` (`llm` or `embedding`; only `llm` entries
  become chat models), `max_context_length`, `params_string`, `quantization.name`,
  `size_bytes`, `capabilities.trained_for_tool_use`, `capabilities.reasoning`, and
  `loaded_instances[]` for residency.

All of these arrive with `discovered` provenance.

### Health
Probes the model listing, then reports **which models are resident** — the difference
between a fast request and a cold load on a local engine.

## Watchlist
- **The native chat API** (`POST /api/v1/chat`) offers stateful threads via
  `previous_response_id`, model-load progress events, per-request `context_length`, and
  ephemeral MCP integrations. Not used today; generation stays on the compatible endpoint.
- Model management (`/api/v1/models/load`, `/unload`, `/download`) — the adapter reads
  inventory but does not manage it. Loading on demand would mirror the llama.cpp
  supervisor and is the obvious next step.
- The deprecated `/api/v0` surface, which older builds expose instead.
- `ttl` (auto-evict) is accepted in request payloads on both surfaces; reachable through
  `provider_options`.
