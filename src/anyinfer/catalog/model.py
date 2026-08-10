"""Alias-catalog schema.

A catalog maps novice-friendly tier aliases (``small``/``medium``/``large``) to concrete
per-provider targets, so an application can offer "pick a size" instead of "pick a model id".
It also carries the **logical model table** — one row per model a user might browse, with the
per-channel sources (a pinned GGUF artifact for the supervised llama.cpp path, a registry tag
for Ollama) and the per-variant sources that hardware-aware quantization choice needs.

Two shapes over the same data, deliberately: the alias ladder answers "just give me a good
default", the model table answers "let me browse and pick". `Catalog.with_alias_target`
bridges them, so a user's pick flows *into* the ladder rather than around it.

The catalog is *data* with its own ``format_version``: applications overlay their own entries
(app wins) and can pin a catalog to insulate themselves from bundled-catalog churn (risk R6).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ConfigError

# Imported from the leaf modules to avoid a cycle: the ``local`` package's recommender
# depends on this module, so importing through the package would be circular. Artifacts and
# source references are leaf data; nothing else in the local subsystem is needed here.
from ..local.artifacts import GgufArtifact, GgufFile
from ..local.sources import SourceRef

__all__ = [
    "BEST_AT",
    "FORMAT_VERSION",
    "AliasEntry",
    "ArtifactKind",
    "Catalog",
    "GgufArtifact",
    "GgufFile",
    "ModelEntry",
    "ModelVariant",
    "OllamaChannel",
    "TargetEntry",
]

FORMAT_VERSION = 1
"""Schema version of the catalog document."""

BEST_AT: frozenset[str] = frozenset(
    {
        "agentic",
        "code-completion",
        "coding",
        "drafting",
        "embeddings",
        "general-chat",
        "long-context",
        "low-resource",
        "math",
        "multilingual",
        "rag",
        "reasoning",
        "tool-use",
        "vision",
    }
)
"""The closed vocabulary of "best at" categories.

Closed on purpose: a free-text tag set drifts into synonyms nobody can filter on. Adding a
category is a deliberate edit here, and the catalog validator enforces the set.
"""

ArtifactKind = str
"""``"gguf"`` (a file set for llama.cpp) or ``"hf_repo"`` (a directory snapshot for vLLM)."""

_ARTIFACT_KINDS = frozenset({"gguf", "hf_repo"})
_ENGINES = frozenset({"llama.cpp", "vllm"})


@dataclass(frozen=True, slots=True)
class TargetEntry:
    """One provider's realization of an alias.

    Attributes:
        provider_id: The provider this target routes to; also its key in the alias's
            target map.
        model: The model reference sent to the provider — a hosted model id or a registry
            tag. An alias target names either a ``model`` or a ``gguf``, never both.
        gguf: Id of a catalog GGUF artifact, for engines that run a local file.
        context_window: Context length declared by the catalog. Overrides detected
            capabilities when the catalog's figure outranks the detected one.
        max_output_tokens: Output-token ceiling declared by the catalog, overriding
            detected capabilities the same way.
        description: Free text for display.
    """

    provider_id: str
    model: str | None = None
    gguf: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    description: str = ""

    @property
    def model_ref(self) -> str:
        """The string that becomes `ResolvedTarget.model`.

        For local engines the alias points at a GGUF artifact id rather than a hosted model
        name; the llama.cpp adapter resolves it through the artifact table.
        """
        ref = self.model or self.gguf
        if not ref:
            raise ConfigError(
                f"catalog entry for provider {self.provider_id!r} has neither 'model' nor 'gguf'",
                hint="every alias target must name a model or a gguf artifact",
            )
        return ref


@dataclass(frozen=True, slots=True)
class AliasEntry:
    """A tier alias and its per-provider targets.

    Attributes:
        name: The alias name, stored lowercase (``"small"``, ``"medium"``, ``"large"``).
        description: Free text for display.
        targets: This tier's realization on each provider, keyed by provider id.
        min_ram_bytes: System RAM this tier is judged to need; the hardware-aware
            recommender skips tiers the machine cannot satisfy.
        min_vram_bytes: Accelerator memory this tier is judged to need, gating the
            recommender the same way.
    """

    name: str
    description: str = ""
    targets: Mapping[str, TargetEntry] = field(default_factory=dict)
    min_ram_bytes: int | None = None
    min_vram_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class OllamaChannel:
    """How a logical model is packaged in the Ollama registry.

    We never download these — the daemon owns its own blob store. The tag is what we
    recommend, and `digest` is what drift checking compares against, because registry tags
    are mutable by design.
    """

    tag: str
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class ModelVariant:
    """One (model, quantization, engine) rung of a model's ladder.

    A variant carries its *own* source reference, because a quantized vLLM variant is
    usually a different repository while a quantized GGUF variant is usually a different
    file in the same repository. One schema covers both only because the reference is per
    variant rather than per model.

    Attributes:
        id: Stable variant id, unique within the catalog.
        engine: ``"llama.cpp"`` or ``"vllm"``.
        kind: ``"gguf"`` or ``"hf_repo"``.
        quantization: The quantization this rung ships (``"Q4_K_M"``, ``"awq"``).
        quality_rank: Ladder position; higher is better quality.
        est_file_bytes: On-disk size of the weights.
        est_ram_bytes: Memory needed on the CPU-only path.
        est_vram_bytes: Memory needed when fully offloaded.
        min_compute_capability: NVIDIA compute capability this variant's kernels need,
            as a string (``"8.9"``). ``None`` means no gate.
        source: Where the bytes come from.
        artifact_id: For GGUF variants, the id under which the derived `GgufArtifact` is
            registered, so alias targets and the llama.cpp adapter can reference it.
    """

    id: str
    engine: str = "llama.cpp"
    kind: str = "gguf"
    quantization: str = ""
    quality_rank: int = 0
    est_file_bytes: int | None = None
    est_ram_bytes: int | None = None
    est_vram_bytes: int | None = None
    min_compute_capability: str | None = None
    source: SourceRef = field(default_factory=SourceRef)
    artifact_id: str | None = None

    @property
    def is_pinned(self) -> bool:
        """Whether every declared file carries a revision and a digest."""
        ref = self.source
        if ref.resolver != "huggingface":
            return bool(ref.urls) and all(ref.digests.get(u.rsplit("/", 1)[-1]) for u in ref.urls)
        if not ref.revision or len(ref.revision) < 40:
            return False
        if not ref.files:
            # A snapshot variant pins its revision; individual file digests come from the
            # tree API at acquisition time and are recorded then.
            return True
        return all(ref.digests.get(name) for name in ref.files)


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """One logical model in the catalog.

    Attributes:
        id: Stable catalog id (``"qwen2.5-7b-instruct"``).
        family: Model family, for grouping in a UI.
        display_name: Human-facing name.
        parameter_size: Parameter class (``"7B"``), keying the KV-cache cost table.
        quantization: The default quantization the headline estimates assume.
        context_window: Native context length, when known.
        license: License id; gated against the download allowlist.
        best_at: Categories from `BEST_AT`.
        est_file_bytes: Download size of the default variant.
        est_ram_bytes: Memory needed on the CPU-only path.
        est_vram_bytes: Memory needed when fully offloaded.
        last_verified: ISO date the entry was actually checked against upstream.
        source: URL of the upstream repository or registry page.
        variants: The quantization ladder, best quality first is *not* assumed — sort by
            `ModelVariant.quality_rank`.
        ollama: The Ollama channel, when the model is published there.
        description: Free text for display.
    """

    id: str
    family: str = ""
    display_name: str = ""
    parameter_size: str | None = None
    quantization: str | None = None
    context_window: int | None = None
    license: str = ""
    best_at: tuple[str, ...] = ()
    est_file_bytes: int | None = None
    est_ram_bytes: int | None = None
    est_vram_bytes: int | None = None
    last_verified: str = ""
    source: str = ""
    variants: tuple[ModelVariant, ...] = ()
    ollama: OllamaChannel | None = None
    description: str = ""

    @property
    def name(self) -> str:
        """Display name, falling back to the id."""
        return self.display_name or self.id

    @property
    def channels(self) -> tuple[str, ...]:
        """Provider ids that can serve this model, sorted."""
        found: set[str] = set()
        for variant in self.variants:
            if variant.engine == "llama.cpp":
                found.add("llama-cpp")
            elif variant.engine == "vllm":
                found.add("vllm")
        if self.ollama is not None:
            found.add("ollama")
        return tuple(sorted(found))

    @property
    def gguf_artifact_id(self) -> str | None:
        """The artifact id of this model's headline GGUF variant, when there is one.

        "Headline" means the quantization the entry's own memory estimates describe — the
        rung a browsing user is being shown — not the highest rung in the repository.
        Picking the largest would quietly hand someone a Q8_0 download after they read a
        Q4_K_M size.
        """
        gguf = [v for v in self.variants if v.kind == "gguf" and v.artifact_id]
        if not gguf:
            return None
        headline = (self.quantization or "").upper()
        for variant in gguf:
            if variant.quantization.upper() == headline:
                return variant.artifact_id
        return max(gguf, key=lambda v: v.quality_rank).artifact_id

    def variants_for(self, engine: str | None = None) -> tuple[ModelVariant, ...]:
        """Variants for one engine, best quality first."""
        chosen = [v for v in self.variants if engine is None or v.engine == engine]
        return tuple(sorted(chosen, key=lambda v: (-v.quality_rank, v.id)))

    def variant(self, variant_id: str) -> ModelVariant:
        """Look up one variant.

        Raises:
            ConfigError: If the variant is unknown.
        """
        for candidate in self.variants:
            if candidate.id == variant_id:
                return candidate
        known = ", ".join(v.id for v in self.variants) or "(none)"
        raise ConfigError(
            f"model {self.id!r} has no variant {variant_id!r}",
            hint=f"known variants: {known}",
        )

    def matches_best_at(self, category: str | None) -> bool:
        """Whether this entry carries a category tag (case-insensitively)."""
        if not category:
            return True
        return category.strip().lower() in self.best_at


@dataclass(frozen=True, slots=True)
class Catalog:
    """A parsed alias catalog.

    Attributes:
        aliases: The tier ladder, keyed by lowercase alias name.
        artifacts: Pinned GGUF artifacts, keyed by artifact id. Includes artifacts derived
            from the model table's GGUF variants as well as explicitly declared ones.
        models: The logical model table, keyed by model id.
        default_alias: The alias resolution falls back to when a caller does not pick one.
        format_version: Schema version of the parsed document.
    """

    aliases: Mapping[str, AliasEntry] = field(default_factory=dict)
    artifacts: Mapping[str, GgufArtifact] = field(default_factory=dict)
    models: Mapping[str, ModelEntry] = field(default_factory=dict)
    default_alias: str = "medium"
    format_version: int = FORMAT_VERSION

    def has_alias(self, name: str) -> bool:
        """Whether an alias exists (case-insensitively)."""
        return name.strip().lower() in self.aliases

    def alias(self, name: str) -> AliasEntry:
        """Look up an alias.

        Raises:
            ConfigError: If the alias is unknown.
        """
        key = name.strip().lower()
        entry = self.aliases.get(key)
        if entry is None:
            known = ", ".join(sorted(self.aliases)) or "(none)"
            raise ConfigError(
                f"unknown alias {name!r}",
                hint=f"known aliases: {known}",
            )
        return entry

    def targets_for_alias(self, name: str) -> Mapping[str, TargetEntry]:
        """Every provider realization of an alias."""
        return self.alias(name).targets

    def artifact(self, artifact_id: str) -> GgufArtifact:
        """Look up a GGUF artifact.

        Raises:
            ConfigError: If the artifact is unknown.
        """
        entry = self.artifacts.get(artifact_id)
        if entry is None:
            known = ", ".join(sorted(self.artifacts)) or "(none)"
            raise ConfigError(
                f"unknown gguf artifact {artifact_id!r}",
                hint=f"known artifacts: {known}",
            )
        return entry

    def alias_names(self) -> tuple[str, ...]:
        """Every alias name, sorted."""
        return tuple(sorted(self.aliases))

    def model(self, model_id: str) -> ModelEntry:
        """Look up a logical model.

        Raises:
            ConfigError: If the model is unknown.
        """
        entry = self.models.get(model_id)
        if entry is None:
            raise ConfigError(
                f"unknown catalog model {model_id!r}",
                hint=f"this catalog defines {len(self.models)} models; check the id",
            )
        return entry

    def models_for(
        self, provider_id: str | None = None, *, best_at: str | None = None
    ) -> tuple[ModelEntry, ...]:
        """Logical models filtered by serving channel and category, id-ordered."""
        channel = provider_id.strip().lower() if provider_id else None
        return tuple(
            entry
            for _, entry in sorted(self.models.items())
            if (channel is None or channel in entry.channels) and entry.matches_best_at(best_at)
        )

    def with_alias_target(self, alias: str, provider_id: str, model_id: str) -> Catalog:
        """Point one alias's provider target at a catalog model.

        This is the bridge between browsing and the tier ladder: an app implements "use my
        catalog pick as `medium`" in one call, and the result resolves through the ordinary
        alias machinery with no resolver changes.

        Raises:
            ConfigError: If the alias or model is unknown, or the model has no artifact for
                the named provider.
        """
        entry = self.alias(alias)
        model = self.model(model_id)
        key = provider_id.strip().lower()

        if key == "ollama":
            if model.ollama is None:
                raise ConfigError(
                    f"catalog model {model_id!r} has no Ollama tag",
                    hint=f"it is available on: {', '.join(model.channels) or '(no channel)'}",
                )
            target = TargetEntry(
                provider_id=key,
                model=model.ollama.tag,
                context_window=model.context_window,
                description=model.name,
            )
        else:
            artifact_id = model.gguf_artifact_id
            if artifact_id is None:
                raise ConfigError(
                    f"catalog model {model_id!r} has no GGUF artifact",
                    hint=f"it is available on: {', '.join(model.channels) or '(no channel)'}",
                )
            target = TargetEntry(
                provider_id=key,
                gguf=artifact_id,
                context_window=model.context_window,
                description=model.name,
            )

        targets = dict(entry.targets)
        targets[key] = target
        aliases = dict(self.aliases)
        aliases[entry.name] = AliasEntry(
            name=entry.name,
            description=entry.description,
            targets=targets,
            min_ram_bytes=entry.min_ram_bytes,
            min_vram_bytes=entry.min_vram_bytes,
        )
        return Catalog(
            aliases=aliases,
            artifacts=self.artifacts,
            models=self.models,
            default_alias=self.default_alias,
            format_version=self.format_version,
        )

    def overlay(self, other: Catalog) -> Catalog:
        """Merge ``other`` on top of this catalog, entry by entry.

        Application entries win over bundled ones at the *alias*, *artifact*, and *model*
        level — an overridden alias replaces the bundled one wholesale rather than merging
        its target map, so an app can remove a provider from a tier it does not want used.
        The same wholesale rule applies per model id.
        """
        aliases = dict(self.aliases)
        aliases.update(other.aliases)
        artifacts = dict(self.artifacts)
        artifacts.update(other.artifacts)
        models = dict(self.models)
        models.update(other.models)
        return Catalog(
            aliases=aliases,
            artifacts=artifacts,
            models=models,
            default_alias=other.default_alias or self.default_alias,
            format_version=max(self.format_version, other.format_version),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Catalog:
        """Parse a catalog document.

        Raises:
            ConfigError: On an unsupported format version or malformed entries.
        """
        version = data.get("format_version", FORMAT_VERSION)
        if not isinstance(version, int) or version > FORMAT_VERSION:
            raise ConfigError(
                f"unsupported catalog format_version {version!r}",
                hint=f"this build understands format_version <= {FORMAT_VERSION}",
            )

        aliases: dict[str, AliasEntry] = {}
        raw_aliases = data.get("aliases", {})
        if not isinstance(raw_aliases, Mapping):
            raise ConfigError("catalog 'aliases' must be an object")
        for name, entry in raw_aliases.items():
            if not isinstance(entry, Mapping):
                raise ConfigError(f"catalog alias {name!r} must be an object")
            aliases[str(name).lower()] = _parse_alias(str(name).lower(), entry)

        artifacts: dict[str, GgufArtifact] = {}
        raw_artifacts = data.get("gguf_artifacts", {})
        if not isinstance(raw_artifacts, Mapping):
            raise ConfigError("catalog 'gguf_artifacts' must be an object")
        for artifact_id, entry in raw_artifacts.items():
            if not isinstance(entry, Mapping):
                raise ConfigError(f"catalog artifact {artifact_id!r} must be an object")
            artifacts[str(artifact_id)] = _parse_artifact(str(artifact_id), entry)

        models: dict[str, ModelEntry] = {}
        raw_models = data.get("models", ())
        if isinstance(raw_models, Mapping):
            raw_models = [{"id": key, **dict(value)} for key, value in raw_models.items()]
        if not isinstance(raw_models, Sequence) or isinstance(raw_models, str):
            raise ConfigError("catalog 'models' must be an array or an object")
        for raw in raw_models:
            if not isinstance(raw, Mapping):
                raise ConfigError("every catalog model must be an object")
            entry_model = _parse_model(raw)
            models[entry_model.id] = entry_model
            # A GGUF variant *is* a pinned artifact; registering the derived form keeps the
            # llama.cpp adapter and alias targets working off one id space rather than two.
            for variant in entry_model.variants:
                artifact = _artifact_from_variant(entry_model, variant)
                if artifact is not None:
                    artifacts.setdefault(artifact.id, artifact)

        return cls(
            aliases=aliases,
            artifacts=artifacts,
            models=models,
            default_alias=str(data.get("default_alias", "medium")),
            format_version=version,
        )

    @classmethod
    def from_files(cls, *paths: Path) -> Catalog:
        """Load several catalog documents and overlay them left to right.

        The bundled catalog is split this way on purpose: ``default.json`` stays a small,
        human-editable alias policy file while ``models.json`` is machine-maintained data
        with its own refresh cadence.

        Raises:
            ConfigError: If any file is missing, malformed, or empty of catalogs.
        """
        if not paths:
            raise ConfigError("no catalog files given")
        merged = cls.from_mapping(_read_json_object(paths[0]))
        for path in paths[1:]:
            merged = merged.overlay(cls.from_mapping(_read_json_object(path)))
        return merged


def _parse_alias(name: str, entry: Mapping[str, Any]) -> AliasEntry:
    raw_targets = entry.get("targets", {})
    if not isinstance(raw_targets, Mapping):
        raise ConfigError(f"catalog alias {name!r} 'targets' must be an object")
    targets: dict[str, TargetEntry] = {}
    for provider_id, target in raw_targets.items():
        if not isinstance(target, Mapping):
            raise ConfigError(f"catalog alias {name!r} target {provider_id!r} must be an object")
        targets[str(provider_id)] = TargetEntry(
            provider_id=str(provider_id),
            model=_opt_str(target.get("model")),
            gguf=_opt_str(target.get("gguf")),
            context_window=_opt_int(target.get("context_window")),
            max_output_tokens=_opt_int(target.get("max_output_tokens")),
            description=str(target.get("description", "")),
        )
    return AliasEntry(
        name=name,
        description=str(entry.get("description", "")),
        targets=targets,
        min_ram_bytes=_opt_int(entry.get("min_ram_bytes")),
        min_vram_bytes=_opt_int(entry.get("min_vram_bytes")),
    )


def _parse_artifact(artifact_id: str, entry: Mapping[str, Any]) -> GgufArtifact:
    raw_files: Sequence[Any]
    if "files" in entry and isinstance(entry["files"], list) and entry["files"]:
        raw_files = entry["files"]
    else:
        raw_files = [entry]

    files: list[GgufFile] = []
    for raw in raw_files:
        if not isinstance(raw, Mapping):
            raise ConfigError(f"catalog artifact {artifact_id!r} has a malformed file entry")
        url = _opt_str(raw.get("url"))
        if not url:
            raise ConfigError(
                f"catalog artifact {artifact_id!r} is missing a download url",
                hint="every gguf artifact file needs a pinned 'url'",
            )
        filename = _opt_str(raw.get("filename")) or url.rsplit("/", 1)[-1]
        role = str(raw.get("role", "model"))
        if role not in ("model", "projector"):
            raise ConfigError(
                f"catalog artifact {artifact_id!r} file {filename!r} has unknown role {role!r}"
            )
        files.append(
            GgufFile(
                filename=filename,
                url=url,
                sha256=str(raw.get("sha256", "")),
                size_bytes=_opt_int(raw.get("size_bytes")),
                role=role,  # type: ignore[arg-type]
            )
        )

    return GgufArtifact(
        id=artifact_id,
        files=tuple(files),
        license=str(entry.get("license", "")),
        description=str(entry.get("description", "")),
        parameter_size=_opt_str(entry.get("parameter_size")),
        quantization=_opt_str(entry.get("quantization")),
        est_ram_bytes=_opt_int(entry.get("est_ram_bytes")),
        est_vram_bytes=_opt_int(entry.get("est_vram_bytes")),
    )


def _read_json_object(path: Path) -> Mapping[str, Any]:
    """Read a JSON object from disk, with catalog-shaped errors."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"cannot read catalog file {path}: {exc}",
            hint="check the path and permissions",
        ) from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ConfigError(f"catalog file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigError(f"catalog file {path} must contain a JSON object")
    return data


def _parse_model(entry: Mapping[str, Any]) -> ModelEntry:
    """Parse one logical model row."""
    model_id = _opt_str(entry.get("id"))
    if not model_id:
        raise ConfigError(
            "every catalog model needs an 'id'",
            hint="model ids are stable, lowercase, and hyphenated",
        )

    raw_tags = entry.get("best_at", ())
    if isinstance(raw_tags, str) or not isinstance(raw_tags, Sequence):
        raise ConfigError(f"catalog model {model_id!r} 'best_at' must be an array")
    tags: list[str] = []
    for tag in raw_tags:
        text = str(tag).strip().lower()
        if text not in BEST_AT:
            raise ConfigError(
                f"catalog model {model_id!r} uses unknown best_at category {text!r}",
                hint=f"known categories: {', '.join(sorted(BEST_AT))}",
            )
        tags.append(text)

    ollama: OllamaChannel | None = None
    raw_sources = entry.get("sources", {})
    if not isinstance(raw_sources, Mapping):
        raise ConfigError(f"catalog model {model_id!r} 'sources' must be an object")
    raw_ollama = raw_sources.get("ollama")
    if isinstance(raw_ollama, Mapping):
        tag = _opt_str(raw_ollama.get("tag"))
        if not tag:
            raise ConfigError(f"catalog model {model_id!r} Ollama channel needs a 'tag'")
        ollama = OllamaChannel(tag=tag, digest=_opt_str(raw_ollama.get("digest")))
    elif isinstance(raw_ollama, str) and raw_ollama:
        ollama = OllamaChannel(tag=raw_ollama)

    raw_variants = entry.get("variants", ())
    if isinstance(raw_variants, str) or not isinstance(raw_variants, Sequence):
        raise ConfigError(f"catalog model {model_id!r} 'variants' must be an array")
    variants = tuple(_parse_variant(model_id, raw) for raw in raw_variants)

    seen: set[str] = set()
    for variant in variants:
        if variant.id in seen:
            raise ConfigError(f"catalog model {model_id!r} repeats variant id {variant.id!r}")
        seen.add(variant.id)

    return ModelEntry(
        id=model_id,
        family=str(entry.get("family", "")),
        display_name=str(entry.get("display_name", "")),
        parameter_size=_opt_str(entry.get("parameter_size")),
        quantization=_opt_str(entry.get("quantization")),
        context_window=_opt_int(entry.get("context_window")),
        license=str(entry.get("license", "")),
        best_at=tuple(tags),
        est_file_bytes=_opt_int(entry.get("est_file_bytes")),
        est_ram_bytes=_opt_int(entry.get("est_ram_bytes")),
        est_vram_bytes=_opt_int(entry.get("est_vram_bytes")),
        last_verified=str(entry.get("last_verified", "")),
        source=str(entry.get("source", "")),
        variants=variants,
        ollama=ollama,
        description=str(entry.get("description", "")),
    )


def _parse_variant(model_id: str, entry: Any) -> ModelVariant:
    """Parse one quantization rung."""
    if not isinstance(entry, Mapping):
        raise ConfigError(f"catalog model {model_id!r} has a malformed variant")
    variant_id = _opt_str(entry.get("id"))
    if not variant_id:
        raise ConfigError(f"catalog model {model_id!r} has a variant with no 'id'")

    engine = str(entry.get("engine", "llama.cpp"))
    if engine not in _ENGINES:
        raise ConfigError(
            f"variant {variant_id!r} names unknown engine {engine!r}",
            hint=f"known engines: {', '.join(sorted(_ENGINES))}",
        )
    kind = str(entry.get("kind", "gguf" if engine == "llama.cpp" else "hf_repo"))
    if kind not in _ARTIFACT_KINDS:
        raise ConfigError(
            f"variant {variant_id!r} names unknown artifact kind {kind!r}",
            hint=f"known kinds: {', '.join(sorted(_ARTIFACT_KINDS))}",
        )

    return ModelVariant(
        id=variant_id,
        engine=engine,
        kind=kind,
        quantization=str(entry.get("quantization", "")),
        quality_rank=_opt_int(entry.get("quality_rank")) or 0,
        est_file_bytes=_opt_int(entry.get("est_file_bytes")),
        est_ram_bytes=_opt_int(entry.get("est_ram_bytes")),
        est_vram_bytes=_opt_int(entry.get("est_vram_bytes")),
        min_compute_capability=_opt_str(entry.get("min_compute_capability")),
        source=_parse_source(variant_id, entry.get("source", {})),
        artifact_id=_opt_str(entry.get("artifact_id")) or (variant_id if kind == "gguf" else None),
    )


def _parse_source(variant_id: str, entry: Any) -> SourceRef:
    """Parse a variant's source reference."""
    if not isinstance(entry, Mapping):
        raise ConfigError(f"variant {variant_id!r} has a malformed 'source'")
    digests_raw = entry.get("sha256", {})
    sizes_raw = entry.get("size_bytes", {})
    roles_raw = entry.get("roles", {})
    if not isinstance(digests_raw, Mapping):
        raise ConfigError(f"variant {variant_id!r} 'source.sha256' must be an object")
    if not isinstance(sizes_raw, Mapping):
        raise ConfigError(f"variant {variant_id!r} 'source.size_bytes' must be an object")
    if not isinstance(roles_raw, Mapping):
        raise ConfigError(f"variant {variant_id!r} 'source.roles' must be an object")
    return SourceRef(
        resolver=str(entry.get("resolver", "huggingface")),
        repo=_opt_str(entry.get("repo")),
        revision=_opt_str(entry.get("revision")),
        files=_str_tuple(entry.get("files")),
        digests={str(k): str(v) for k, v in digests_raw.items()},
        sizes={str(k): int(v) for k, v in sizes_raw.items() if isinstance(v, int)},
        roles={str(k): str(v) for k, v in roles_raw.items()},
        urls=_str_tuple(entry.get("urls")),
        include=_str_tuple(entry.get("include")),
        exclude=_str_tuple(entry.get("exclude")),
        path=_opt_str(entry.get("path")),
    )


def _artifact_from_variant(model: ModelEntry, variant: ModelVariant) -> GgufArtifact | None:
    """Derive the pinned artifact a GGUF variant describes, when it is complete enough."""
    if variant.kind != "gguf" or not variant.artifact_id:
        return None
    ref = variant.source
    files: list[GgufFile] = []
    if ref.resolver == "huggingface" and ref.repo and ref.revision:
        for name in ref.files:
            files.append(
                GgufFile(
                    filename=name.rsplit("/", 1)[-1],
                    url=f"https://huggingface.co/{ref.repo}/resolve/{ref.revision}/{name}",
                    sha256=ref.digests.get(name, ""),
                    size_bytes=ref.sizes.get(name),
                    role=("projector" if ref.roles.get(name) == "projector" else "model"),
                )
            )
    else:
        for url in ref.urls:
            name = url.rsplit("/", 1)[-1]
            files.append(
                GgufFile(
                    filename=name,
                    url=url,
                    sha256=ref.digests.get(name, ""),
                    size_bytes=ref.sizes.get(name),
                    role=("projector" if ref.roles.get(name) == "projector" else "model"),
                )
            )
    if not files:
        return None
    return GgufArtifact(
        id=variant.artifact_id,
        files=tuple(files),
        license=model.license,
        description=model.name,
        parameter_size=model.parameter_size,
        quantization=variant.quantization or model.quantization,
        est_ram_bytes=variant.est_ram_bytes or model.est_ram_bytes,
        est_vram_bytes=variant.est_vram_bytes or model.est_vram_bytes,
    )


def _str_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        return ()
    return tuple(str(item) for item in value if str(item))


def _opt_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _opt_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
