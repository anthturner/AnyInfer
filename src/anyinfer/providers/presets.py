"""Branded presets over the OpenAI-compatible dialect (`contracts/openai-compat-presets.md`).

One implementation, many brandings. Every provider here speaks the chat-completions
dialect closely enough that the shared `OpenAICompatAdapter` covers it; what differs is
declarative — endpoint, auth spelling, output-token parameter name, whether ``GET
/models`` exists, reasoning-effort translation, and which parameters are silently
ignored. Each preset therefore registers as a first-class provider (``groq:``,
``together:``, ``vllm:`` …) built from a data entry rather than a new adapter module.

Providers with real protocol deltas get dedicated adapters instead (Gemini, Vertex,
Bedrock, Cohere, DeepSeek, xAI, LM Studio) — the dividing line is whether the wire
behavior differs, not the brand. Some services fail that line outright and are
deliberately absent: Writer serves ``POST /v1/chat`` rather than ``/chat/completions``.
watsonx.ai's *native* API is likewise out of reach (body-level project scoping, a version
query parameter, a separate streaming path), but its OpenAI-compatible model gateway is a
preset — IBM's own example passes a Cloud API key straight through, and an exchanged IAM
token works too at the cost of having to refresh it. The contract snapshot records the
details.

Endpoint and quirk data was verified against each provider's live documentation; the
per-provider details and verification dates live in the contract snapshot.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

from ..registry import (
    HostShorthand,
    ProviderDescriptor,
    ProviderSetupSpec,
    SetupField,
)
from ..types.capabilities import Feature, Health, ModelCapabilities, Sourced
from ..types.requests import ReasoningEffort
from .base import ProviderConfig, WireRequest
from .openai_compat import OpenAICompatAdapter

__all__ = [
    "COMPAT_PRESETS",
    "CompatPreset",
    "PresetCompatAdapter",
    "ReasoningStyle",
    "preset_descriptors",
]

_DEFAULT_FEATURES = Feature.STREAMING | Feature.TOOLS | Feature.SYSTEM_PROMPT
"""What any OpenAI-compatible endpoint is assumed to handle, matching ``openai-compat``."""

ReasoningStyle = Literal[
    "effort", "effort-min-low", "effort-three-level", "effort-min-named", "reasoning-object"
]
"""Reasoning-field dialect used by an OpenAI-compatible preset."""
"""How a preset spells reasoning effort on the wire.

- ``effort``: a top-level ``reasoning_effort`` string, all four normalized levels accepted.
- ``effort-min-low``: as above, but the provider documents no ``minimal`` level, so
  ``minimal`` maps to ``low`` rather than being rejected.
- ``effort-three-level``: providers publishing and validating a three-value
  ``low``/``medium``/``high`` enum, so ``minimal`` clamps to ``low``.
- ``effort-min-named``: as ``effort``, but the lowest level is spelled ``min`` rather
  than ``minimal`` (Requesty).
- ``reasoning-object``: a ``reasoning: {"effort": …}`` object (Vercel's AI Gateway).
"""


@dataclass(frozen=True, slots=True)
class CompatPreset:
    """Declarative facts for one OpenAI-compatible provider.

    Attributes:
        id: Canonical provider id, also the target prefix (``groq:``).
        display_name: Human-readable name for UIs.
        base_url: Default API root, or ``None`` when the user must supply one.
        aliases: Alternate ids accepted anywhere a provider id is.
        locality: ``hosted`` services need a key; ``local`` engines default to loopback.
        key_env: Conventional environment variable for the API key, used in help text.
        requires_api_key: Whether requests fail without a credential.
        accepts_api_key: Whether a credential can be sent at all when one is not required.
            True for the ordinary keyless local engine, which authenticates once its
            operator starts it with ``--api-key`` or puts a reverse proxy in front of it.
            False only where a credential provably would not travel in the header the
            adapter sends: Lemonade documents an ``?api_key=`` query parameter, and Docker
            Model Runner ignores ``Authorization`` outright. Offering a key field there
            would take a value, send it, and still fail to authenticate.
        requires_base_url: Whether a base URL must be supplied (self-hosted, per-account).
        base_url_hint: Help text describing the expected base URL shape.
        models_listing: Whether ``GET /models`` exists. Without it, discovery returns
            empty and the health probe reports optimistically rather than always-failing.
        auth_header: ``bearer`` (``Authorization: Bearer``) or ``x-api-key``.
        output_tokens_field: Wire name for the output-token cap.
        features: Capability flags beyond the conservative compat defaults.
        ignored_parameters: Request parameters the provider accepts and discards,
            surfaced as `ParameterDropped` telemetry.
        reasoning: How reasoning effort is spelled, or ``None`` when the provider has no
            documented control (use ``provider_options`` for provider-specific spellings).
        default_port: Port used by the local host shorthand (``myhost`` →
            ``http://myhost:PORT``).
        note: One-line quirk summary, rendered into the generated provider index.
    """

    id: str
    display_name: str
    base_url: str | None
    aliases: tuple[str, ...] = ()
    locality: Literal["hosted", "local"] = "hosted"
    key_env: str = ""
    requires_api_key: bool = True
    accepts_api_key: bool = True
    requires_base_url: bool = False
    base_url_hint: str = ""
    models_listing: bool = True
    auth_header: Literal["bearer", "x-api-key"] = "bearer"
    output_tokens_field: str = "max_tokens"
    features: Feature = _DEFAULT_FEATURES
    ignored_parameters: tuple[str, ...] = ()
    reasoning: ReasoningStyle | None = None
    default_port: int | None = None
    note: str = ""


class PresetCompatAdapter(OpenAICompatAdapter):
    """The shared adapter, specialized by a preset's declarative quirks."""

    def __init__(self, config: ProviderConfig, *, preset: CompatPreset) -> None:
        self._preset = preset
        super().__init__(config)

    def _build_headers(self, config: ProviderConfig) -> dict[str, str]:
        """Spell the credential the way this provider expects."""
        if self._preset.auth_header == "bearer":
            return super()._build_headers(config)
        headers = {"content-type": "application/json"}
        if config.api_key:
            headers["x-api-key"] = config.api_key
        headers.update({k.lower(): v for k, v in config.headers.items()})
        return headers

    def build_payload(self, req: WireRequest) -> dict[str, Any]:
        """Rename the output-token parameter for dialects that moved it."""
        payload = super().build_payload(req)
        field = self._preset.output_tokens_field
        if field != "max_tokens" and "max_tokens" in payload:
            payload[field] = payload.pop("max_tokens")
        return payload

    async def list_models(self) -> Sequence[Any]:
        """List models, or report none where the provider has no listing endpoint."""
        if not self._preset.models_listing:
            return []
        return await super().list_models()

    async def health(self) -> Health:
        """Probe via the model listing, or answer optimistically without one.

        A provider with no cheap read-only endpoint cannot be probed without spending
        a generation. Reporting healthy keeps the router from gating it out; a real
        failure still marks it unhealthy the moment a request fails.
        """
        if not self._preset.models_listing:
            return Health(ok=True, detail="no cheap readiness probe; failures surface on use")
        return await super().health()


def _translate_effort(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """``reasoning_effort`` pass-through for providers accepting all four levels."""
    return {} if effort is None else {"reasoning_effort": effort}


def _translate_effort_min_low(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """``reasoning_effort`` with ``minimal`` mapped to the provider's lowest level."""
    if effort is None:
        return {}
    return {"reasoning_effort": "low" if effort == "minimal" else effort}


def _translate_effort_three_level(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """``reasoning_effort`` for providers documenting only low/medium/high.

    Identical in effect to ``effort-min-low`` today, since ``minimal`` is the only
    normalized level below ``low``. It stays a separate style because the underlying
    documentation differs: these providers publish a three-value enum and validate it,
    whereas ``effort-min-low`` providers merely omit ``minimal`` from a longer ladder.
    Conflating them would lose that distinction the next time either enum moves.
    """
    if effort is None:
        return {}
    return {"reasoning_effort": "low" if effort == "minimal" else effort}


def _translate_effort_min_named(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """``reasoning_effort`` where the lowest level is spelled ``min``, not ``minimal``.

    Requesty documents ``min`` (a synonym for ``none``) alongside low/medium/high.
    Clamping onto ``low`` like the other translators would work but would quietly ask
    for more reasoning than the caller wanted, so the near-homograph is worth honoring.
    """
    if effort is None:
        return {}
    return {"reasoning_effort": "min" if effort == "minimal" else effort}


def _translate_reasoning_object(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """The gateway-normalized ``reasoning`` object (Vercel AI Gateway)."""
    return {} if effort is None else {"reasoning": {"effort": effort}}


def _no_reasoning(effort: ReasoningEffort | None) -> Mapping[str, Any]:
    """Presets without a documented control send nothing; use ``provider_options``."""
    return {}


_TRANSLATORS = {
    None: _no_reasoning,
    "effort": _translate_effort,
    "effort-min-low": _translate_effort_min_low,
    "effort-three-level": _translate_effort_three_level,
    "effort-min-named": _translate_effort_min_named,
    "reasoning-object": _translate_reasoning_object,
}


COMPAT_PRESETS: tuple[CompatPreset, ...] = (
    # ---- hosted fast-inference clouds ------------------------------------------------
    CompatPreset(
        id="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        note="LPU-served open models; rejects logprobs/logit_bias-style parameters.",
    ),
    CompatPreset(
        id="cerebras",
        display_name="Cerebras Inference",
        base_url="https://api.cerebras.ai/v1",
        key_env="CEREBRAS_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING | Feature.CACHE_USAGE,
        reasoning="effort-min-low",
        note="Wafer-scale speed; combining tools with response_format is model-dependent.",
    ),
    CompatPreset(
        id="sambanova",
        display_name="SambaNova Cloud",
        base_url="https://api.sambanova.ai/v1",
        key_env="SAMBANOVA_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING | Feature.CACHE_USAGE,
        reasoning="effort-min-low",
        note="Model listing reports live per-model pricing and context metadata.",
    ),
    # ---- hosted open-model catalogs --------------------------------------------------
    CompatPreset(
        id="together",
        display_name="Together AI",
        base_url="https://api.together.ai/v1",
        aliases=("together-ai",),
        key_env="TOGETHER_API_KEY",
        features=_DEFAULT_FEATURES | Feature.JSON_SCHEMA | Feature.JSON_MODE
        | Feature.REASONING,
        reasoning="effort-min-low",
        note="Large open-model catalog; org/model ids (e.g. deepseek-ai/…).",
    ),
    CompatPreset(
        id="fireworks",
        display_name="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        aliases=("fireworks-ai",),
        key_env="FIREWORKS_API_KEY",
        features=_DEFAULT_FEATURES | Feature.JSON_SCHEMA | Feature.JSON_MODE
        | Feature.REASONING,
        reasoning="effort",
        note="Model ids look like accounts/fireworks/models/…; over-long max_tokens is "
        "silently truncated unless context_length_exceeded_behavior='error'.",
    ),
    CompatPreset(
        id="deepinfra",
        display_name="DeepInfra",
        base_url="https://api.deepinfra.com/v1/openai",
        key_env="DEEPINFRA_API_KEY",
        features=_DEFAULT_FEATURES | Feature.JSON_MODE | Feature.REASONING,
        reasoning="effort-min-low",
        note="Pay-per-token open models; service_tier extension for priority/flex.",
    ),
    CompatPreset(
        id="novita",
        display_name="Novita AI",
        base_url="https://api.novita.ai/openai/v1",
        aliases=("novita-ai",),
        key_env="NOVITA_API_KEY",
        note="max_tokens is required by the API; reasoning models stream "
        "reasoning_content.",
    ),
    CompatPreset(
        id="hyperbolic",
        display_name="Hyperbolic",
        base_url="https://api.hyperbolic.xyz/v1",
        key_env="HYPERBOLIC_API_KEY",
        note="Open-model serving; reasoning models emit inline <think> content.",
    ),
    CompatPreset(
        id="baseten",
        display_name="Baseten Model APIs",
        base_url="https://inference.baseten.co/v1",
        key_env="BASETEN_API_KEY",
        note="Fixed shared catalog; model listing reports pricing and context metadata.",
    ),
    CompatPreset(
        id="featherless",
        display_name="Featherless AI",
        base_url="https://api.featherless.ai/v1",
        key_env="FEATHERLESS_API_KEY",
        note="Very large HF-repo-id catalog, case-sensitive; subscription plans are "
        "concurrency-limited rather than token-metered.",
    ),
    CompatPreset(
        id="parasail",
        display_name="Parasail",
        base_url="https://api.parasail.io/v1",
        key_env="PARASAIL_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-three-level",
        note="parasail- prefixed model ids; per-model thinking controls "
        "(chat_template_kwargs, thinking_budget) via provider_options.",
    ),
    CompatPreset(
        id="chutes",
        display_name="Chutes",
        base_url="https://llm.chutes.ai/v1",
        key_env="CHUTES_API_KEY",
        note="Decentralized open-model serving. The model field doubles as a routing "
        "directive ('default', or a comma-separated fallback list) — pass those "
        "verbatim as the target's model. The catalog at /v1/models is unauthenticated.",
    ),
    CompatPreset(
        id="avian",
        display_name="Avian",
        base_url="https://api.avian.io/v1",
        key_env="AVIAN_API_KEY",
        note="Keys carry a literal avian- prefix, which is part of the key rather than "
        "something to strip. The unauthenticated /v1/models listing reports context "
        "length and pricing.",
    ),
    CompatPreset(
        id="inference-net",
        display_name="Inference.net",
        base_url="https://api.inference.net/v1",
        aliases=("inference",),
        key_env="INFERENCE_API_KEY",
        note="Serverless ids plus team/model deployments; BYOK passthrough via "
        "provider headers.",
    ),
    CompatPreset(
        id="nscale",
        display_name="Nscale",
        base_url="https://inference.api.nscale.com/v1",
        key_env="NSCALE_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort",
        note="No enforced rate limits; model listing reports pricing and context "
        "length. tool_choice supports only auto/none.",
    ),
    CompatPreset(
        id="scaleway",
        display_name="Scaleway Generative APIs",
        base_url="https://api.scaleway.ai/v1",
        key_env="SCW_SECRET_KEY",
        ignored_parameters=("frequency_penalty", "n", "top_logprobs", "logit_bias"),
        note="EU-sovereign; ids carry quantization suffixes (:fp8, :int4). "
        "presence_penalty is supported but frequency_penalty is not.",
    ),
    CompatPreset(
        id="venice",
        display_name="Venice AI",
        base_url="https://api.venice.ai/api/v1",
        key_env="VENICE_API_KEY",
        output_tokens_field="max_completion_tokens",
        features=_DEFAULT_FEATURES | Feature.REASONING | Feature.JSON_SCHEMA,
        reasoning="effort",
        note="Privacy-focused; max_tokens is deprecated in favour of "
        "max_completion_tokens. Web search and thinking controls via "
        "provider_options ({'venice_parameters': …}).",
    ),
    CompatPreset(
        id="upstage",
        display_name="Upstage (Solar)",
        base_url="https://api.upstage.ai/v1",
        aliases=("solar",),
        key_env="UPSTAGE_API_KEY",
        models_listing=False,
        features=_DEFAULT_FEATURES | Feature.REASONING | Feature.CACHE_USAGE,
        reasoning="effort",
        note="Solar family; reasoning_effort semantics differ per model — solar-mini "
        "rejects the parameter entirely, solar-open2 reasons unless disabled.",
    ),
    CompatPreset(
        id="reka",
        display_name="Reka AI",
        base_url="https://api.reka.ai/v1",
        key_env="REKA_API_KEY",
        auth_header="x-api-key",
        note="Multimodal (image/video/audio). The HTTP reference documents x-api-key "
        "for chat; tool_choice spells the forced case 'tool', not 'required'.",
    ),
    CompatPreset(
        id="nous",
        display_name="Nous Research (Portal)",
        base_url="https://inference-api.nousresearch.com/v1",
        aliases=("nousresearch", "hermes"),
        key_env="NOUS_API_KEY",
        models_listing=False,
        note="Hermes models, capitalized ids (Hermes-4-405B). max_tokens defaults to "
        "100 — set it explicitly or output truncates.",
    ),
    CompatPreset(
        id="arcee",
        display_name="Arcee AI",
        base_url="https://api.arcee.ai/api/v1",
        key_env="ARCEE_API_KEY",
        note="Trinity models; the Conductor router (models.arcee.ai/v1) accepts "
        "model='auto' as a base-URL override.",
    ),
    # ---- frontier-adjacent hosted providers ------------------------------------------
    CompatPreset(
        id="mistral",
        display_name="Mistral AI (La Plateforme)",
        base_url="https://api.mistral.ai/v1",
        aliases=("mistral-ai",),
        key_env="MISTRAL_API_KEY",
        features=_DEFAULT_FEATURES | Feature.JSON_SCHEMA | Feature.JSON_MODE
        | Feature.REASONING,
        reasoning="effort",
        note="Uses random_seed instead of seed; safe_prompt via provider_options.",
    ),
    CompatPreset(
        id="perplexity",
        display_name="Perplexity Sonar",
        base_url="https://api.perplexity.ai",
        key_env="PERPLEXITY_API_KEY",
        features=Feature.STREAMING | Feature.SYSTEM_PROMPT | Feature.JSON_SCHEMA
        | Feature.JSON_MODE | Feature.REASONING,
        ignored_parameters=("tools",),
        reasoning="effort",
        note="Grounded web search built in; search_results ride on the raw payload "
        "(retain_raw=True), search filters via provider_options.",
    ),
    CompatPreset(
        id="moonshot",
        display_name="Moonshot AI (Kimi)",
        base_url="https://api.moonshot.ai/v1",
        aliases=("kimi",),
        key_env="MOONSHOT_API_KEY",
        output_tokens_field="max_completion_tokens",
        note="Kimi model family; thinking controls via provider_options "
        "({'thinking': …}).",
    ),
    CompatPreset(
        id="z-ai",
        display_name="Z.ai (Zhipu GLM)",
        base_url="https://api.z.ai/api/paas/v4",
        # Not "zhipu": that is the company behind both this international host and the
        # mainland bigmodel one, so the bare name would have to pick a side silently.
        # Callers name the platform they hold a key for; the keys do not cross.
        aliases=("zai", "glm"),
        key_env="ZAI_API_KEY",
        models_listing=False,
        note="GLM model family; temperature range is 0-1, thinking controls via "
        "provider_options ({'thinking': {'type': …}}).",
    ),
    CompatPreset(
        id="dashscope",
        display_name="Alibaba Model Studio (Qwen)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        aliases=("qwen", "alibaba-qwen", "model-studio"),
        key_env="DASHSCOPE_API_KEY",
        models_listing=False,
        note="International endpoint; keys are region-specific. Thinking controls via "
        "provider_options ({'enable_thinking': …, 'thinking_budget': …}).",
    ),
    CompatPreset(
        id="minimax",
        display_name="MiniMax",
        base_url="https://api.minimax.io/v1",
        key_env="MINIMAX_API_KEY",
        models_listing=False,
        output_tokens_field="max_completion_tokens",
        note="M-series models; thinking controls via provider_options "
        "({'thinking': {'type': …}}).",
    ),
    CompatPreset(
        id="ai21",
        display_name="AI21 Labs",
        base_url="https://api.ai21.com/studio/v1",
        key_env="AI21_API_KEY",
        models_listing=False,
        note="Jamba model family; max_tokens caps at 4096.",
    ),
    # ---- routers and gateways --------------------------------------------------------
    CompatPreset(
        id="huggingface",
        display_name="Hugging Face Inference Providers",
        base_url="https://router.huggingface.co/v1",
        aliases=("hf", "huggingface-router"),
        key_env="HF_TOKEN",
        note="Routes HF-hub model ids across serving partners; append :provider to pin "
        "one (e.g. moonshotai/Kimi-K2-Instruct:groq).",
    ),
    CompatPreset(
        id="nvidia",
        display_name="NVIDIA NIM (build.nvidia.com)",
        base_url="https://integrate.api.nvidia.com/v1",
        aliases=("nim", "nvidia-nim"),
        key_env="NVIDIA_API_KEY",
        note="Hosted NIM catalog; self-hosted NIM containers expose the same surface "
        "on your own base URL.",
    ),
    CompatPreset(
        id="vercel-ai-gateway",
        display_name="Vercel AI Gateway",
        base_url="https://ai-gateway.vercel.sh/v1",
        aliases=("vercel", "ai-gateway"),
        key_env="AI_GATEWAY_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="reasoning-object",
        note="creator/model ids across upstream providers; gateway-normalized "
        "reasoning object.",
    ),
    CompatPreset(
        id="cloudflare-workers-ai",
        display_name="Cloudflare Workers AI",
        base_url=None,
        aliases=("workers-ai", "cloudflare"),
        key_env="CLOUDFLARE_API_TOKEN",
        requires_base_url=True,
        base_url_hint=(
            "https://api.cloudflare.com/client/v4/accounts/<account_id>/ai/v1"
        ),
        models_listing=False,
        note="@cf/author/model ids; the base URL embeds your account id.",
    ),
    CompatPreset(
        id="digitalocean",
        display_name="DigitalOcean Inference",
        base_url="https://inference.do-ai.run/v1",
        aliases=("do-inference", "digitalocean-inference"),
        key_env="MODEL_ACCESS_KEY",
        output_tokens_field="max_completion_tokens",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-min-low",
        note="Serverless catalog on a fixed host; model-access keys are scopable "
        "per-model. Vendor prefixes on ids are inconsistent — read the listing.",
    ),
    CompatPreset(
        id="ovhcloud",
        display_name="OVHcloud AI Endpoints",
        base_url="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        aliases=("ovh",),
        key_env="OVH_AI_ENDPOINTS_ACCESS_TOKEN",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-three-level",
        note="EU-hosted unified gateway. Model ids are load-bearing and irregularly "
        "punctuated (Meta-Llama-3_3-70B-Instruct) — never normalize them.",
    ),
    CompatPreset(
        id="snowflake-cortex",
        display_name="Snowflake Cortex",
        base_url=None,
        aliases=("cortex", "snowflake"),
        key_env="SNOWFLAKE_PAT",
        requires_base_url=True,
        base_url_hint=(
            "https://<account-identifier>.snowflakecomputing.com/api/v2/cortex/v1"
        ),
        models_listing=False,
        output_tokens_field="max_completion_tokens",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort",
        note="Base URL embeds your account identifier; authenticate with a programmatic "
        "access token. n, presence_penalty, logprobs, stop and logit_bias are ignored.",
        ignored_parameters=("n", "presence_penalty", "logprobs", "stop", "logit_bias"),
    ),
    CompatPreset(
        id="databricks",
        display_name="Databricks Model Serving",
        base_url=None,
        aliases=("mosaic",),
        key_env="DATABRICKS_TOKEN",
        requires_base_url=True,
        base_url_hint="https://<workspace-host>/serving-endpoints",
        models_listing=False,
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort",
        note="Base URL is your workspace host; a personal access token authenticates. "
        "Usage rides on every stream chunk rather than only the last.",
    ),
    CompatPreset(
        id="oci-genai",
        display_name="Oracle OCI Generative AI",
        base_url=None,
        aliases=("oci", "oracle"),
        key_env="OCI_GENAI_API_KEY",
        requires_base_url=True,
        base_url_hint=(
            "https://inference.generativeai.<region>.oci.oraclecloud.com/openai/v1"
        ),
        models_listing=False,
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort",
        note="Base URL is region-templated. The OpenAI-compatible surface takes a "
        "service-specific key and covers a subset of the catalog; request signing "
        "remains the production path for the native API.",
    ),
    CompatPreset(
        id="litellm",
        display_name="LiteLLM Proxy",
        base_url=None,
        aliases=("litellm-proxy",),
        requires_api_key=False,
        requires_base_url=True,
        base_url_hint="http://your-proxy-host:4000",
        note="Self-hosted gateway over 100+ providers; authenticate with a "
        "proxy-issued virtual key.",
    ),
    CompatPreset(
        id="portkey",
        display_name="Portkey AI Gateway",
        base_url="https://api.portkey.ai/v1",
        key_env="PORTKEY_API_KEY",
        models_listing=False,
        note="Routing, caching and fallbacks over many providers. Selecting the "
        "upstream needs x-portkey-* headers (provider, config); pass them as "
        "configured headers. Point base_url at your own host when self-hosting.",
    ),
    CompatPreset(
        id="requesty",
        display_name="Requesty Router",
        base_url="https://router.requesty.ai/v1",
        key_env="REQUESTY_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-min-named",
        note="vendor/model ids across many upstreams. Reports usage.cost in USD on "
        "buffered responses; streaming needs stream_options.include_usage for it.",
    ),
    CompatPreset(
        id="martian",
        display_name="Martian Gateway",
        base_url="https://api.withmartian.com/v1",
        key_env="MARTIAN_API_KEY",
        note="creator/model ids; routes across upstream providers.",
    ),
    CompatPreset(
        id="helicone",
        display_name="Helicone AI Gateway",
        base_url="https://ai-gateway.helicone.ai",
        aliases=("helicone-gateway",),
        key_env="HELICONE_API_KEY",
        note="Routing with observability. The provider suffix *follows* the model "
        "(gpt-4o-mini/openai), inverting the vendor/model order most routers use — a "
        "bare id lets the gateway choose, and listed ids are bare. Legacy /completions "
        "is unsupported. Under credit billing the accepted request schema is narrower "
        "than OpenAI's; bringing your own key restores the full one.",
    ),
    # ---- regional and enterprise clouds ----------------------------------------------
    CompatPreset(
        id="volcengine",
        display_name="BytePlus ModelArk (Volcengine Ark)",
        base_url="https://ark.ap-southeast.bytepluses.com/api/v3",
        aliases=("ark", "doubao", "bytedance"),
        key_env="ARK_API_KEY",
        models_listing=False,
        note="International (BytePlus) endpoint; the mainland edition is a separate "
        "account and host (ark.cn-beijing.volces.com/api/v3). Doubao models. Thinking "
        "controls go through provider_options ({'thinking': …}).",
    ),
    CompatPreset(
        id="qianfan",
        display_name="Baidu Qianfan (ERNIE)",
        base_url="https://qianfan.baidubce.com/v2",
        aliases=("baidu", "ernie"),
        key_env="QIANFAN_API_KEY",
        note="v2 takes a single permanent bearer key shaped bce-v3/ALTAK-<id>/<secret> — "
        "pass it whole, since the embedded slashes are part of the key. Do not mix it "
        "with the deprecated v1 AK/SK OAuth flow; that pairing is the usual integration "
        "failure. Thinking is parameter-driven and spelled per model family "
        "('thinking' or 'enable_thinking') via provider_options.",
    ),
    CompatPreset(
        id="hunyuan",
        display_name="Tencent Hunyuan",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        aliases=("tencent",),
        key_env="HUNYUAN_API_KEY",
        models_listing=False,
        note="Reasoning is mostly a model choice (the hunyuan-t1-* line), though "
        "hunyuan-a13b instead toggles it in-prompt with a /no_think prefix. Beware "
        "`stop`: Hunyuan halts *after* the matched string where OpenAI halts before it, "
        "so the stop sequence appears in the output. Search and multimedia toggles go "
        "through provider_options.",
    ),
    CompatPreset(
        id="spark",
        display_name="iFlytek Spark",
        base_url="https://spark-api-open.xf-yun.com/v1",
        aliases=("iflytek",),
        key_env="SPARK_API_PASSWORD",
        models_listing=False,
        note="The HTTP surface takes a single bearer APIPassword from the console — "
        "not the legacy AppID/APIKey/APISecret triple, which belongs to the WebSocket "
        "path and does not work here. The console renders that password in an "
        "APIKey:APISecret shape; paste it whole rather than splitting on the colon.",
    ),
    CompatPreset(
        id="stepfun",
        display_name="StepFun",
        base_url="https://api.stepfun.com/v1",
        aliases=("step",),
        key_env="STEP_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-three-level",
        note="Step models. The subscription surface is a different path on the same "
        "host (/step_plan/v1), so point base_url there for plan traffic — billing "
        "differs. Its Anthropic-compatible endpoint is /step_plan without the /v1, "
        "which the Anthropic SDK appends itself.",
    ),
    CompatPreset(
        id="watsonx",
        display_name="IBM watsonx.ai (model gateway)",
        base_url=None,
        aliases=("ibm-watsonx",),
        key_env="WATSONX_API_KEY",
        requires_base_url=True,
        base_url_hint="https://<region>.ml.cloud.ibm.com/ml/gateway/v1",
        note="The OpenAI-compatible model gateway (beta, IBM Cloud only), which "
        "sidesteps the native API's request-body project scoping and version pinning — "
        "providers are registered per project ahead of time instead. IBM's own example "
        "passes the Cloud API key straight through as api_key; an exchanged IAM bearer "
        "token also works, but then it expires and the client must refresh. Models are "
        "addressed provider-namespaced (openai/gpt-4o).",
    ),
    # ---- local engines and self-hosted servers ---------------------------------------
    CompatPreset(
        id="vllm",
        display_name="vLLM",
        base_url="http://127.0.0.1:8000/v1",
        locality="local",
        requires_api_key=False,
        default_port=8000,
        note="Serves one model per process; engine extras (guided decoding, top_k) via "
        "provider_options.",
    ),
    CompatPreset(
        id="sglang",
        display_name="SGLang",
        base_url="http://127.0.0.1:30000/v1",
        locality="local",
        requires_api_key=False,
        default_port=30000,
        note="Engine extras (separate_reasoning, top_k, min_p) via provider_options.",
    ),
    CompatPreset(
        id="koboldcpp",
        display_name="KoboldCpp",
        base_url="http://127.0.0.1:5001/v1",
        aliases=("kobold",),
        locality="local",
        requires_api_key=False,
        default_port=5001,
        note="OpenAI-compatible surface beside the native Kobold API on one port; "
        "sampler extensions via provider_options.",
    ),
    CompatPreset(
        id="jan",
        display_name="Jan",
        base_url="http://127.0.0.1:1337/v1",
        locality="local",
        requires_api_key=False,
        default_port=1337,
        note="Desktop app's local API server (enable it in Jan's settings).",
    ),
    CompatPreset(
        id="gpt4all",
        display_name="GPT4All",
        base_url="http://localhost:4891/v1",
        locality="local",
        requires_api_key=False,
        default_port=4891,
        features=Feature.SYSTEM_PROMPT,
        note="Minimal local server (enable in settings); no streaming or tool calling "
        "documented.",
    ),
    CompatPreset(
        id="text-generation-webui",
        display_name="text-generation-webui",
        base_url="http://127.0.0.1:5000/v1",
        aliases=("oobabooga", "textgen-webui"),
        locality="local",
        requires_api_key=False,
        default_port=5000,
        note="Start with --api; the model listing reports only the loaded model.",
    ),
    CompatPreset(
        id="localai",
        display_name="LocalAI",
        base_url="http://127.0.0.1:8080/v1",
        aliases=("local-ai",),
        locality="local",
        requires_api_key=False,
        default_port=8080,
        note="Serves many models at once; ids are gallery names or GGUF filenames. "
        "Optional auth accepts Authorization, x-api-key, or xi-api-key.",
    ),
    CompatPreset(
        id="llamafile",
        display_name="llamafile",
        base_url="http://127.0.0.1:8080/v1",
        locality="local",
        requires_api_key=False,
        default_port=8080,
        note="Single self-contained executable serving one model; examples report the "
        "model id as the literal string LLaMA_CPP.",
    ),
    CompatPreset(
        id="tgi",
        display_name="Text Generation Inference",
        base_url="http://127.0.0.1:3000/v1",
        aliases=("text-generation-inference",),
        locality="local",
        requires_api_key=False,
        models_listing=False,
        default_port=3000,
        note="Hugging Face's server, default port 3000. Serves one model, addressed as "
        "the literal id 'tgi'; the Messages API needs TGI 1.4.0 or newer.",
    ),
    CompatPreset(
        id="aphrodite",
        display_name="Aphrodite Engine",
        base_url="http://127.0.0.1:2242/v1",
        locality="local",
        requires_api_key=False,
        default_port=2242,
        note="vLLM fork with extra samplers, on port 2242 rather than vLLM's 8000; "
        "sampler extensions via provider_options.",
    ),
    CompatPreset(
        id="mlc-llm",
        display_name="MLC-LLM",
        base_url="http://127.0.0.1:8000/v1",
        aliases=("mlc",),
        locality="local",
        requires_api_key=False,
        default_port=8000,
        note="Compiled-model serving (mlc_llm serve); documents /v1/models and "
        "/v1/chat/completions only.",
    ),
    CompatPreset(
        id="openllm",
        display_name="OpenLLM",
        base_url="http://127.0.0.1:3000/v1",
        locality="local",
        requires_api_key=False,
        default_port=3000,
        note="BentoML's server on port 3000; one model per process, launched as "
        "'openllm serve model:version'.",
    ),
    CompatPreset(
        id="triton",
        display_name="NVIDIA Triton (OpenAI frontend)",
        base_url="http://127.0.0.1:9000/v1",
        aliases=("triton-openai",),
        locality="local",
        requires_api_key=False,
        default_port=9000,
        note="The OpenAI frontend listens on 9000 — port 8000 is Triton's own KServe "
        "HTTP endpoint, not this one.",
    ),
    CompatPreset(
        id="xinference",
        display_name="Xinference",
        base_url="http://127.0.0.1:9997/v1",
        aliases=("xorbits",),
        locality="local",
        requires_api_key=False,
        default_port=9997,
        note="Serves many models at once; ids are the model UIDs you launched. Cluster "
        "mode puts the same API on the supervisor host.",
    ),
    CompatPreset(
        id="ramalama",
        display_name="RamaLama",
        base_url="http://127.0.0.1:8080/v1",
        locality="local",
        requires_api_key=False,
        default_port=8080,
        note="Container-based runner. The port is only a starting point: if 8080 is "
        "taken it picks the next free one, so check what `ramalama serve` printed "
        "rather than assuming.",
    ),
    CompatPreset(
        id="geniex",
        display_name="GenieX (formerly Nexa SDK)",
        base_url="http://127.0.0.1:18181/v1",
        aliases=("nexa",),
        locality="local",
        requires_api_key=False,
        default_port=18181,
        note="On-device Snapdragon inference, now published by Qualcomm as GenieX — the "
        "CLI is `geniex serve`, not the older `nexa serve`. The server ignores the "
        "credential but rejects an empty one, so send any non-empty string. Only one "
        "tool call per assistant turn is parsed.",
    ),
    CompatPreset(
        id="tabbyapi",
        display_name="TabbyAPI",
        base_url="http://127.0.0.1:5000/v1",
        aliases=("tabby",),
        locality="local",
        requires_api_key=False,
        default_port=5000,
        auth_header="x-api-key",
        note="ExLlama-family serving; inference calls use the x-api-key header.",
    ),
    # ---- fourth wave (2026-08-08): aggregators, regional clouds, more engines --------
    CompatPreset(
        id="poe",
        display_name="Poe (Quora)",
        base_url="https://api.poe.com/v1",
        key_env="POE_API_KEY",
        ignored_parameters=("parallel_tool_calls",),
        note="Hundreds of models and community bots behind one subscription. Model ids "
        "are bot names and are capitalized (Claude-Sonnet-4.6). n must be 1, "
        "parallel_tool_calls is unsupported, audio input is ignored, and json_schema "
        "response_format is not supported — the weakest structured-output mechanism "
        "wins here. Private bots are unreachable through this endpoint.",
    ),
    CompatPreset(
        id="siliconflow",
        display_name="SiliconFlow",
        base_url="https://api.siliconflow.com/v1",
        aliases=("silicon-flow",),
        key_env="SILICONFLOW_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        note="The .com host serves the international account; api.siliconflow.cn is the "
        "mainland one and keys are not interchangeable. Thinking is parameter-driven "
        "via provider_options ({'enable_thinking': …, 'thinking_budget': 128-32768}) "
        "and defaults to ON — DeepSeek-V3.1 needs it false for function calling.",
    ),
    CompatPreset(
        id="ppio",
        display_name="PPIO",
        base_url="https://api.ppio.com/openai",
        aliases=("ppinfra",),
        key_env="PPIO_API_KEY",
        models_listing=False,
        note="Formerly PPInfra: the host moved to api.ppio.com/openai, and the widely "
        "copied api.ppinfra.com/v3/openai is the legacy spelling. Model ids are "
        "vendor-namespaced (deepseek/deepseek-r1) and a /community suffix marks the "
        "free trial tier of the same weights.",
    ),
    CompatPreset(
        id="modelscope",
        display_name="ModelScope (API-Inference)",
        base_url="https://api-inference.modelscope.cn/v1",
        aliases=("ms-inference",),
        key_env="MODELSCOPE_SDK_TOKEN",
        note="Alibaba's model community. The credential is an SDK access token shaped "
        "ms-<uuid>, not a console API key. Ids are HF-style org/model repo paths. The "
        "free tier is capped per day rather than per minute.",
    ),
    CompatPreset(
        id="bigmodel",
        display_name="Zhipu BigModel (GLM, mainland)",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        aliases=("zhipu-cn",),
        key_env="ZHIPU_API_KEY",
        models_listing=False,
        note="The mainland platform behind GLM, and a separate account from z-ai: keys "
        "do not cross between them. temperature is an open interval (0,1) — 0 and 1 are "
        "both rejected, where OpenAI accepts them. Thinking via provider_options "
        "({'thinking': {'type': 'enabled'}}).",
    ),
    CompatPreset(
        id="inception",
        display_name="Inception (Mercury)",
        base_url="https://api.inceptionlabs.ai/v1",
        aliases=("mercury",),
        key_env="INCEPTION_API_KEY",
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-three-level",
        note="Diffusion LLMs rather than autoregressive ones, which shows up in the "
        "stream: with provider_options {'diffusing': True} the model emits blocks of "
        "noisy tokens that are refined in place, so deltas revise earlier text instead "
        "of only appending. Those tokens are not billed. Also serves /fim/completions.",
    ),
    CompatPreset(
        id="sarvam",
        display_name="Sarvam AI",
        base_url="https://api.sarvam.ai/v1",
        key_env="SARVAM_API_KEY",
        models_listing=False,
        features=_DEFAULT_FEATURES | Feature.REASONING,
        reasoning="effort-three-level",
        note="Indic-language models. Its own header is api-subscription-key, but a "
        "bearer token is accepted for OpenAI compatibility and is what this preset "
        "sends. Reasoning is ON at 'low' by default — pass an explicit null through "
        "provider_options to disable it. Open-weight models live on /v2 instead.",
    ),
    CompatPreset(
        id="clarifai",
        display_name="Clarifai",
        base_url="https://api.clarifai.com/v2/ext/openai/v1",
        key_env="CLARIFAI_PAT",
        models_listing=False,
        note="The credential is a personal access token, not a per-app key. Model ids "
        "are catalog paths (openai/chat-completion/models/gpt-oss-120b) and the full "
        "clarifai.com URL form is accepted too.",
    ),
    CompatPreset(
        id="lighton",
        display_name="LightOn Paradigm",
        base_url="https://paradigm.lighton.ai/api/v2",
        aliases=("paradigm",),
        key_env="LIGHTON_API_KEY",
        note="EU document-intelligence platform. The base path is /api/v2, not /v1.",
    ),
    CompatPreset(
        id="ollama-cloud",
        display_name="Ollama Cloud",
        base_url="https://ollama.com/v1",
        aliases=("ollama-turbo",),
        key_env="OLLAMA_API_KEY",
        note="Ollama's hosted catalog, distinct from the local ollama: adapter and "
        "needing a real key. Model ids drop the -cloud suffix here: gpt-oss:120b-cloud "
        "is how a local Ollama proxies it, gpt-oss:120b is what this host wants.",
    ),
    CompatPreset(
        id="runpod",
        display_name="Runpod Serverless",
        base_url=None,
        key_env="RUNPOD_API_KEY",
        requires_base_url=True,
        base_url_hint="https://api.runpod.ai/v2/<endpoint_id>/openai/v1",
        note="The base URL embeds your serverless endpoint id. vLLM extras (top_k, "
        "best_of, guided decoding) ride through provider_options; set RAW_OPENAI_OUTPUT "
        "on the worker if streaming chunks arrive misshapen.",
    ),
    CompatPreset(
        id="vast-ai",
        display_name="Vast.ai Serverless",
        base_url=None,
        aliases=("vast",),
        key_env="VAST_API_KEY",
        requires_base_url=True,
        base_url_hint="https://openai.vast.ai/<endpoint_name>",
        models_listing=False,
        note="The base URL ends in your endpoint name and carries no /v1. The model "
        "field is required by the protocol but ignored by the proxy — the endpoint's "
        "own MODEL_NAME decides what runs, so send any non-empty string.",
    ),
    CompatPreset(
        id="cloudflare-ai-gateway",
        display_name="Cloudflare AI Gateway (unified)",
        base_url=None,
        aliases=("cf-ai-gateway",),
        key_env="CF_AIG_TOKEN",
        requires_base_url=True,
        base_url_hint=(
            "https://gateway.ai.cloudflare.com/v1/<account_id>/<gateway_id>/compat"
        ),
        models_listing=False,
        note="The multi-provider gateway, not Workers AI: it fronts OpenAI, Anthropic, "
        "Groq and others behind provider/model ids. Distinct from "
        "cloudflare-workers-ai, which serves only @cf/ models. Cloudflare's own token "
        "goes in cf-aig-authorization, so send it as a configured header when the "
        "upstream also needs its own key in Authorization.",
    ),
    CompatPreset(
        id="hyperstack",
        display_name="Hyperstack AI Studio",
        base_url=None,
        key_env="HYPERSTACK_API_KEY",
        requires_base_url=True,
        base_url_hint="https://console.hyperstack.cloud/ai/api/v1",
        note="Base URL and model id are both read off the AI Studio playground's API "
        "panel, since they follow your deployment rather than a fixed catalog.",
    ),
    CompatPreset(
        id="nutanix",
        display_name="Nutanix Enterprise AI",
        base_url=None,
        aliases=("nai",),
        key_env="NUTANIX_API_KEY",
        requires_base_url=True,
        base_url_hint="https://<nai-endpoint-host>/api/v1",
        note="On-prem GPT-in-a-Box deployments; the host is your own cluster endpoint.",
    ),
    CompatPreset(
        id="llama-stack",
        display_name="Llama Stack",
        base_url="http://127.0.0.1:8321/v1",
        aliases=("llamastack",),
        locality="local",
        requires_api_key=False,
        default_port=8321,
        note="Meta's server, fronting vLLM/Ollama/hosted backends. Current builds serve "
        "OpenAI routes at /v1; older ones nested them under /v1/openai/v1, so check the "
        "path before blaming the key. Also speaks the Anthropic Messages shape at "
        "/v1/messages.",
    ),
    CompatPreset(
        id="kserve",
        display_name="KServe",
        base_url=None,
        locality="local",
        requires_api_key=False,
        requires_base_url=True,
        base_url_hint="http://<service-host>/openai/v1",
        note="Kubernetes model serving. The OpenAI routes sit behind an /openai prefix "
        "by default — the usual 404 here is a base URL ending in /v1 alone. Clusters "
        "that set KSERVE_OPENAI_ROUTE_PREFIX empty do want the bare /v1.",
    ),
    CompatPreset(
        id="lemonade",
        display_name="Lemonade Server",
        base_url="http://127.0.0.1:13305/v1",
        locality="local",
        requires_api_key=False,
        accepts_api_key=False,
        default_port=13305,
        note="AMD-sponsored server with Ryzen AI NPU backends. Note the credential is "
        "not a bearer token: when LEMONADE_API_KEY is set the server wants it as an "
        "?api_key= query parameter. Also serves the Ollama and Anthropic shapes on the "
        "same port.",
    ),
    CompatPreset(
        id="docker-model-runner",
        display_name="Docker Model Runner",
        base_url="http://127.0.0.1:12434/engines/v1",
        aliases=("dmr",),
        locality="local",
        requires_api_key=False,
        accepts_api_key=False,
        default_port=12434,
        note="Built into Docker Desktop. The OpenAI routes live under /engines/v1, not "
        "/v1. From inside a container the host is model-runner.docker.internal. The "
        "Authorization header is ignored entirely.",
    ),
    CompatPreset(
        id="llama-swap",
        display_name="llama-swap",
        base_url="http://127.0.0.1:8080/v1",
        locality="local",
        requires_api_key=False,
        default_port=8080,
        note="A proxy that swaps the upstream llama-server/vLLM process to match each "
        "request's model field, so the model id is a config profile name rather than a "
        "file. Swapping unloads the previous model, which makes the first request after "
        "a switch slow rather than failed.",
    ),
    CompatPreset(
        id="foundry-local",
        display_name="Microsoft Foundry Local",
        base_url=None,
        # Deliberately no "foundry" alias: azure-foundry owns that name, and Foundry
        # Local is the on-device product rather than a shorthand for the cloud one.
        aliases=("foundry-local-service",),
        locality="local",
        requires_api_key=False,
        requires_base_url=True,
        base_url_hint="http://127.0.0.1:<port>/v1 — see `foundry service status`",
        # Its listing lives at /openai/models and returns a bare array of names rather
        # than an OpenAI {"object": "list", "data": [...]} envelope, so pointing
        # discovery at /v1/models would 404 and parsing the real route would fail.
        models_listing=False,
        note="On-device ONNX serving. The port is assigned dynamically at service "
        "start, so it must be read from `foundry service status` or GET /openai/status "
        "rather than assumed — 5273 and 5272 both appear in Microsoft's own examples. "
        "Requests need the full model id (Phi-4-mini-instruct-generic-cpu), not the CLI "
        "alias, and models unload after ten idle minutes by default.",
    ),
)
"""Every registered preset, hosted then local. Data source: the contract snapshot."""


def _setup_spec(preset: CompatPreset) -> ProviderSetupSpec:
    """Build the declarative config-UI spec for one preset.

    Which of the two fields a user is actually asked for depends on the preset, and the
    two cases are mirror images. A hosted service knows its endpoint and not your key, so
    the key is the question and the URL folds away. A local engine knows neither — but its
    address has a conventional default and its credential usually does not exist at all,
    so *both* fold away and adding it asks nothing.
    """
    fields: list[SetupField] = []
    if preset.requires_api_key or preset.locality == "hosted" or preset.accepts_api_key:
        optional_local = not preset.requires_api_key and preset.locality == "local"
        hint = "Accepts a literal, env://VAR, or credential://system/name."
        if optional_local:
            hint = f"Only needed if this server was started with authentication. {hint}"
        if preset.key_env:
            hint = f"Conventionally env://{preset.key_env}. {hint}"
        fields.append(
            SetupField(
                key="api_key",
                label="API key",
                kind="secret",
                required=preset.requires_api_key,
                # A local engine's credential is the exception rather than the setup step:
                # keyless is how these ship, and a key exists only once someone turned
                # authentication on. Hosted keys stay in front of the user.
                advanced=optional_local,
                help_text=hint,
                # The preset table already knows this provider's conventional variable,
                # so the example in an empty editor can name it rather than leaving a UI
                # to guess — and a guess is necessarily some *other* provider's spelling.
                placeholder=(
                    f"env://{preset.key_env} or a literal key"
                    if preset.key_env
                    else "env://VARIABLE_NAME or a literal key"
                ),
            )
        )
    url_help = preset.base_url_hint or (
        f"Defaults to {preset.base_url}." if preset.base_url else ""
    )
    fields.append(
        SetupField(
            key="base_url",
            label="Base URL",
            kind="endpoint",
            required=preset.requires_base_url,
            # A preset with a default endpoint has already answered this question; one
            # whose URL embeds an account id, endpoint id, or cluster host has not, and
            # that is exactly the set that declares ``requires_base_url``.
            advanced=preset.base_url is not None and not preset.requires_base_url,
            default_value=preset.base_url or "",
            help_text=url_help,
            placeholder=preset.base_url or "",
        )
    )
    shorthand = None
    if preset.default_port is not None:
        shorthand = HostShorthand(scheme="http", default_port=preset.default_port)
    return ProviderSetupSpec(
        fields=tuple(fields),
        model_selection="discover-or-manual" if preset.models_listing else "manual-only",
        host_shorthand=shorthand,
    )


def _descriptor(preset: CompatPreset) -> ProviderDescriptor:
    """Materialize one preset into a registrable descriptor."""
    return ProviderDescriptor(
        id=preset.id,
        display_name=preset.display_name,
        aliases=preset.aliases,
        factory=partial(PresetCompatAdapter, preset=preset),
        locality=preset.locality,
        default_base_url=preset.base_url,
        requires_base_url=preset.requires_base_url,
        setup=_setup_spec(preset),
        default_capabilities=ModelCapabilities(
            features=Sourced(preset.features, "default")
        ),
        ignored_parameters=preset.ignored_parameters,
        reasoning_translator=_TRANSLATORS[preset.reasoning],
    )


def preset_descriptors() -> Iterator[ProviderDescriptor]:
    """Yield a descriptor for every preset, in table order."""
    for preset in COMPAT_PRESETS:
        yield _descriptor(preset)
