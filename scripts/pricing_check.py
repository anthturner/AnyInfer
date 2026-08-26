"""Pure records, parsers, comparison, and reporting for pricing drift checks.

This module deliberately contains no networking imports. Live retrieval is isolated in
``pricing_fetch.py`` so every normalization and money comparison is deterministic and
offline-testable.

**Scope: per-token rates only.** The table also carries per-invocation rates for
provider-run tools (``server_tools``), and nothing here watches them. Every admitted feed
is a *model* catalog publishing prompt and completion prices; a search fee is a separate
line item those catalogs do not carry in a comparable form. So a server-tool rate is
verified when a human reads the provider's own pricing page and is not re-checked
afterwards. Those rates move — every one currently recorded was read on 2026-08-25 — so
the staleness risk here is real rather than theoretical.

That is a real gap rather than a decision to be comfortable with, and it is recorded here
because the alternative is a report that looks exhaustive while silently covering less
than it appears to. `validate_pricing.py` still holds those rates to the same date and
source discipline as a token rate, so what is missing is the *drift tripwire*, not the
provenance requirement. Revisit if an admitted feed begins publishing per-invocation fees
in a comparable form.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

Authority = Literal["direct", "secondary"]
FindingStatus = Literal[
    "match",
    "price-drift",
    "upstream-missing",
    "not-comparable",
    "unchecked",
    "source-failed",
]
PolicyMode = Literal[
    "direct", "secondary", "manual", "authenticated", "unrepresentable", "deferred"
]


@dataclass(frozen=True, slots=True)
class BundledRate:
    """One provider-and-model keyed bundled price selected for a checker."""

    provider: str
    model: str
    input_per_1m: Decimal
    output_per_1m: Decimal
    last_verified: str
    authority_url: str
    check_id: str | None = None


@dataclass(frozen=True, slots=True)
class RateObservation:
    """A source-labelled, normalized upstream price observation."""

    checker: str
    authority: Authority
    upstream_id: str
    input_per_1m: Decimal
    output_per_1m: Decimal
    currency: str
    tier: str
    evidence_url: str


@dataclass(frozen=True, slots=True)
class DriftFinding:
    """Comparison outcome for one selected bundled entry."""

    status: FindingStatus
    bundled: BundledRate
    observation: RateObservation | None
    reason: str


@dataclass(frozen=True, slots=True)
class ProviderPricingPolicy:
    """Declared deterministic-check posture for one bundled provider."""

    provider: str
    mode: PolicyMode
    checker: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """A hard-coded machine-readable source and its pure protocol parser."""

    name: str
    authority: Authority
    url: str
    parser: Callable[[Mapping[str, Any]], dict[str, RateObservation]]


@dataclass(frozen=True, slots=True)
class SourceResult:
    """Completion state for one enabled source."""

    checker: str
    authority: Authority
    evidence_url: str
    selected_entries: int
    observations: int
    success: bool
    error: str = ""


OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
CHUTES_URL = "https://llm.chutes.ai/v1/models"
AVIAN_URL = "https://api.avian.io/v1/models"


def _decimal(value: object, *, field: str) -> Decimal:
    """Convert a JSON string/integer/Decimal without ever accepting a float."""
    if isinstance(value, (bool, float)):
        raise ValueError(f"{field} must be a decimal string or exact JSON number")
    if not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{field} is missing or not numeric")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} is not a decimal") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be a finite non-negative decimal")
    return result


def _rows(payload: Mapping[str, Any], *, source: str) -> Sequence[object]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"{source}: expected a data array")
    return rows


def parse_openrouter(payload: Mapping[str, Any]) -> dict[str, RateObservation]:
    """Parse OpenRouter per-token USD strings into USD per million tokens."""
    observations: dict[str, RateObservation] = {}
    for raw in _rows(payload, source="openrouter-models"):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
            continue
        pricing = raw.get("pricing")
        if not isinstance(pricing, Mapping):
            continue
        try:
            prompt = _decimal(pricing.get("prompt"), field="pricing.prompt")
            completion = _decimal(pricing.get("completion"), field="pricing.completion")
        except ValueError:
            continue
        upstream_id = raw["id"]
        observations[upstream_id] = RateObservation(
            checker="openrouter-models",
            authority="secondary",
            upstream_id=upstream_id,
            input_per_1m=prompt * Decimal(1_000_000),
            output_per_1m=completion * Decimal(1_000_000),
            currency="USD",
            tier="standard",
            evidence_url=OPENROUTER_URL,
        )
    return observations


def parse_chutes(payload: Mapping[str, Any]) -> dict[str, RateObservation]:
    """Parse Chutes' flat USD-per-million prompt and completion fields."""
    observations: dict[str, RateObservation] = {}
    for raw in _rows(payload, source="chutes-models"):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
            continue
        pricing = raw.get("pricing")
        if not isinstance(pricing, Mapping):
            continue
        try:
            prompt = _decimal(pricing.get("prompt"), field="pricing.prompt")
            completion = _decimal(pricing.get("completion"), field="pricing.completion")
        except ValueError:
            continue
        upstream_id = raw["id"]
        observations[upstream_id] = RateObservation(
            checker="chutes-models",
            authority="direct",
            upstream_id=upstream_id,
            input_per_1m=prompt,
            output_per_1m=completion,
            currency="USD",
            tier="standard",
            evidence_url=CHUTES_URL,
        )
    return observations


def parse_avian(payload: Mapping[str, Any]) -> dict[str, RateObservation]:
    """Parse Avian's explicit USD-per-million input and output fields."""
    observations: dict[str, RateObservation] = {}
    for raw in _rows(payload, source="avian-models"):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
            continue
        pricing = raw.get("pricing")
        if not isinstance(pricing, Mapping):
            continue
        try:
            prompt = _decimal(pricing.get("input_per_million"), field="pricing.input_per_million")
            completion = _decimal(
                pricing.get("output_per_million"), field="pricing.output_per_million"
            )
        except ValueError:
            continue
        upstream_id = raw["id"]
        observations[upstream_id] = RateObservation(
            checker="avian-models",
            authority="direct",
            upstream_id=upstream_id,
            input_per_1m=prompt,
            output_per_1m=completion,
            currency="USD",
            tier="standard",
            evidence_url=AVIAN_URL,
        )
    return observations


SOURCES: dict[str, SourceDefinition] = {
    "openrouter-models": SourceDefinition(
        "openrouter-models", "secondary", OPENROUTER_URL, parse_openrouter
    ),
    "chutes-models": SourceDefinition("chutes-models", "direct", CHUTES_URL, parse_chutes),
    "avian-models": SourceDefinition("avian-models", "direct", AVIAN_URL, parse_avian),
}


def _policy(
    provider: str, mode: PolicyMode, reason: str, checker: str | None = None
) -> ProviderPricingPolicy:
    return ProviderPricingPolicy(provider, mode, checker, reason)


PROVIDER_POLICIES: dict[str, ProviderPricingPolicy] = {
    "openai": _policy(
        "openai",
        "secondary",
        "OpenRouter is a tripwire; OpenAI documentation is authority",
        "openrouter-models",
    ),
    "anthropic": _policy(
        "anthropic",
        "secondary",
        "OpenRouter is a tripwire; Anthropic documentation is authority",
        "openrouter-models",
    ),
    "chutes": _policy(
        "chutes",
        "direct",
        "public provider-owned listing exposes comparable USD token rates",
        "chutes-models",
    ),
    "avian": _policy(
        "avian",
        "direct",
        "public provider-owned listing exposes comparable USD token rates",
        "avian-models",
    ),
    "gemini": _policy("gemini", "manual", "context tiers require provider-page verification"),
    "cerebras": _policy("cerebras", "manual", "no admitted stable public pricing feed"),
    "sambanova": _policy(
        "sambanova", "authenticated", "model pricing listing requires credentials"
    ),
    "together": _policy("together", "manual", "no admitted stable public pricing feed"),
    "fireworks": _policy("fireworks", "manual", "no admitted stable public pricing feed"),
    "deepinfra": _policy("deepinfra", "manual", "no admitted stable public pricing feed"),
    "baseten": _policy("baseten", "authenticated", "model pricing listing requires credentials"),
    "mistral": _policy("mistral", "manual", "provider page remains the verified authority"),
    "perplexity": _policy(
        "perplexity", "unrepresentable", "search and request fees are not represented"
    ),
    "moonshot": _policy("moonshot", "manual", "no admitted exact first-party mapping"),
    "z-ai": _policy("z-ai", "manual", "no admitted stable public pricing feed"),
    "dashscope": _policy(
        "dashscope", "manual", "regional and tier dimensions require manual verification"
    ),
    "minimax": _policy("minimax", "manual", "no admitted stable public pricing feed"),
    "ai21": _policy("ai21", "manual", "provider page remains the verified authority"),
    "deepseek": _policy(
        "deepseek", "manual", "cache and service-tier dimensions require manual verification"
    ),
    "xai": _policy("xai", "authenticated", "machine-readable model pricing requires credentials"),
    "cohere": _policy("cohere", "manual", "provider page remains the verified authority"),
    "bedrock": _policy(
        "bedrock", "deferred", "region and deployment SKU are not represented by the table key"
    ),
    "vertex": _policy(
        "vertex", "deferred", "region and deployment SKU are not represented by the table key"
    ),
    "venice": _policy("venice", "manual", "large catalog has no admitted stable pricing feed"),
    "reka": _policy("reka", "manual", "provider page remains the verified authority"),
    "upstage": _policy("upstage", "manual", "provider page remains the verified authority"),
    "arcee": _policy("arcee", "manual", "provider page remains the verified authority"),
    "digitalocean": _policy(
        "digitalocean", "manual", "regional service dimensions require manual verification"
    ),
    "qianfan": _policy("qianfan", "authenticated", "model pricing listing requires credentials"),
    "stepfun": _policy(
        "stepfun",
        "unrepresentable",
        "published rates are CNY and currency conversion is not represented",
    ),
    "voyage": _policy(
        "voyage", "manual", "no machine-readable pricing feed; provider page is the authority"
    ),
}


def load_bundled(data: Mapping[str, Any]) -> list[BundledRate]:
    """Load all bundled entries using exact Decimal strings."""
    providers = data.get("providers")
    if not isinstance(providers, Mapping):
        raise ValueError("pricing table has no providers object")
    rates: list[BundledRate] = []
    for provider, raw_entries in providers.items():
        if not isinstance(provider, str) or not isinstance(raw_entries, list):
            raise ValueError("pricing provider entries must be arrays")
        for raw in raw_entries:
            if not isinstance(raw, Mapping):
                raise ValueError(f"{provider}: pricing entry must be an object")
            rates.append(
                BundledRate(
                    provider=provider,
                    model=str(raw["model"]),
                    input_per_1m=_decimal(raw["input_per_1m"], field="input_per_1m"),
                    output_per_1m=_decimal(raw["output_per_1m"], field="output_per_1m"),
                    last_verified=str(raw["last_verified"]),
                    authority_url=str(raw["source"]),
                    check_id=str(raw["openrouter_id"]) if raw.get("openrouter_id") else None,
                )
            )
    return rates


def selected_rates(rates: Sequence[BundledRate], checker: str) -> list[BundledRate]:
    """Select exact bundled entries for one registered checker."""
    if checker == "openrouter-models":
        return [rate for rate in rates if rate.check_id is not None]
    if checker == "chutes-models":
        return [rate for rate in rates if rate.provider == "chutes"]
    if checker == "avian-models":
        return [rate for rate in rates if rate.provider == "avian"]
    raise ValueError(f"unknown pricing checker {checker!r}")


def compare_rates(
    bundled: Sequence[BundledRate],
    observations: Mapping[str, RateObservation],
    *,
    checker: str,
) -> list[DriftFinding]:
    """Purely compare exact selected IDs and return stable ordered findings."""
    findings: list[DriftFinding] = []
    for rate in bundled:
        upstream_id = rate.check_id if checker == "openrouter-models" else rate.model
        observation = observations.get(upstream_id or "")
        if observation is None:
            findings.append(
                DriftFinding(
                    "upstream-missing",
                    rate,
                    None,
                    (
                        f"exact mapped model {upstream_id!r} is absent from a successful "
                        "source response"
                    ),
                )
            )
        elif observation.currency != "USD" or observation.tier != "standard":
            findings.append(
                DriftFinding(
                    "not-comparable", rate, observation, "currency or service tier does not match"
                )
            )
        elif (
            rate.input_per_1m != observation.input_per_1m
            or rate.output_per_1m != observation.output_per_1m
        ):
            sides = []
            if rate.input_per_1m != observation.input_per_1m:
                sides.append("input")
            if rate.output_per_1m != observation.output_per_1m:
                sides.append("output")
            findings.append(
                DriftFinding(
                    "price-drift", rate, observation, f"{' and '.join(sides)} rate differs"
                )
            )
        else:
            findings.append(DriftFinding("match", rate, observation, "rates match exactly"))
    return sorted(findings, key=lambda item: (item.bundled.provider, item.bundled.model, checker))


def failed_findings(
    bundled: Sequence[BundledRate], *, checker: str, reason: str
) -> list[DriftFinding]:
    """Represent an unavailable source without pretending all models disappeared."""
    return [
        DriftFinding("source-failed", rate, None, f"{checker}: {reason}")
        for rate in sorted(bundled, key=lambda item: (item.provider, item.model))
    ]


def validate_policies(rates: Sequence[BundledRate]) -> list[str]:
    """Validate exhaustive policies and phase-one non-regression coverage."""
    problems: list[str] = []
    providers = {rate.provider for rate in rates}
    policy_providers = set(PROVIDER_POLICIES)
    for provider in sorted(providers - policy_providers):
        problems.append(f"{provider}: no pricing coverage policy")
    for provider in sorted(policy_providers - providers):
        problems.append(f"{provider}: coverage policy has no bundled provider")
    for provider, policy in sorted(PROVIDER_POLICIES.items()):
        if not policy.reason.strip():
            problems.append(f"{provider}: coverage policy reason is empty")
        if policy.mode in {"direct", "secondary"}:
            if not policy.checker or policy.checker not in SOURCES:
                problems.append(f"{provider}: checked policy names an unknown checker")
            elif not [
                rate for rate in selected_rates(rates, policy.checker) if rate.provider == provider
            ]:
                problems.append(f"{provider}: checked policy selects no bundled entries")
        elif policy.checker is not None:
            problems.append(f"{provider}: unchecked policy must not name a checker")

    direct_keys: set[tuple[str, str]] = set()
    checked_keys: set[tuple[str, str]] = set()
    checked_providers: set[str] = set()
    for policy in PROVIDER_POLICIES.values():
        if policy.checker:
            chosen = [
                r for r in selected_rates(rates, policy.checker) if r.provider == policy.provider
            ]
            keys = {(r.provider, r.model) for r in chosen}
            checked_keys.update(keys)
            checked_providers.update(provider for provider, _ in keys)
            if policy.mode == "direct":
                direct_keys.update(keys)
    if len(direct_keys) < 23:
        problems.append(f"direct pricing coverage regressed below 23 entries ({len(direct_keys)})")
    if len(checked_keys) < 33:
        problems.append(f"total pricing coverage regressed below 33 entries ({len(checked_keys)})")
    if len(checked_providers) < 4:
        problems.append(f"checked pricing providers regressed below 4 ({len(checked_providers)})")
    if len(SOURCES) < 3:
        problems.append(f"pricing source implementations regressed below 3 ({len(SOURCES)})")
    return problems


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def build_report(
    *,
    checked_at: str,
    all_rates: Sequence[BundledRate],
    findings: Sequence[DriftFinding],
    source_results: Sequence[SourceResult],
) -> dict[str, Any]:
    """Build the versioned stable report mapping."""
    ordered = sorted(
        findings,
        key=lambda item: (
            item.bundled.provider,
            item.bundled.model,
            item.observation.checker if item.observation else item.reason.split(":", 1)[0],
        ),
    )
    checked = [item for item in ordered if item.status not in {"source-failed", "unchecked"}]
    direct_keys = {
        (item.bundled.provider, item.bundled.model)
        for item in checked
        if item.observation and item.observation.authority == "direct"
    }
    secondary_keys = {
        (item.bundled.provider, item.bundled.model)
        for item in checked
        if item.observation and item.observation.authority == "secondary"
    }
    finding_rows: list[dict[str, Any]] = []
    for item in ordered:
        row: dict[str, Any] = {
            "provider": item.bundled.provider,
            "model": item.bundled.model,
            "status": item.status,
            "bundled_input_per_1m": _decimal_text(item.bundled.input_per_1m),
            "bundled_output_per_1m": _decimal_text(item.bundled.output_per_1m),
            "authority_url": item.bundled.authority_url,
            "reason": item.reason,
        }
        if item.observation:
            row.update(
                {
                    "checker": item.observation.checker,
                    "authority": item.observation.authority,
                    "upstream_id": item.observation.upstream_id,
                    "observed_input_per_1m": _decimal_text(item.observation.input_per_1m),
                    "observed_output_per_1m": _decimal_text(item.observation.output_per_1m),
                    "evidence_url": item.observation.evidence_url,
                }
            )
        finding_rows.append(row)
    coverage = [asdict(PROVIDER_POLICIES[name]) for name in sorted(PROVIDER_POLICIES)]
    return {
        "format_version": 1,
        "checked_at": checked_at,
        "summary": {
            "bundled_entries": len(all_rates),
            "checked_entries": len(direct_keys | secondary_keys),
            "direct_entries": len(direct_keys),
            "secondary_entries": len(secondary_keys),
            "drift": sum(item.status in {"price-drift", "upstream-missing"} for item in ordered),
            "source_failures": sum(not result.success for result in source_results),
        },
        "sources": [
            asdict(item) for item in sorted(source_results, key=lambda item: item.checker)
        ],
        "findings": finding_rows,
        "coverage": coverage,
    }


def render_json(report: Mapping[str, Any]) -> str:
    """Render a byte-stable JSON report."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_text(report: Mapping[str, Any]) -> str:
    """Render concise human output from the same structured report."""
    summary = report["summary"]
    lines = [
        (
            f"Pricing check: {summary['checked_entries']}/{summary['bundled_entries']} entries "
            f"({summary['direct_entries']} direct, {summary['secondary_entries']} secondary); "
            f"{summary['drift']} drift; {summary['source_failures']} source failures."
        )
    ]
    for row in report["findings"]:
        if row["status"] == "match":
            continue
        checker = row.get("checker", row["reason"].split(":", 1)[0])
        authority = row.get("authority", "unavailable")
        identity = f"{row['provider']}:{row['model']}"
        lines.append(f"{row['status']}: {identity} [{checker}, {authority}] — {row['reason']}")
    return "\n".join(lines) + "\n"
