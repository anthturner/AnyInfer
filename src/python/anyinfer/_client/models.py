"""Browsing the local model catalog, and acquiring what a user picks.

The two client-facing halves of local model management. Browsing answers *what could I
run, and would it fit?*; acquisition answers *get me that one, and tell me where it went*.
Both are shared by the async client and its synchronous facade, which is why they live
here rather than in either one.

The honest-unknown rule runs through both. A remote Ollama daemon runs on a machine we
cannot probe, so its catalog comes back with every fit ``unknown`` and
``hardware_source="unavailable"`` — a machine-readable cue for the application to ask the
user for the remote host's specs and call again with
`HardwareProfile.from_user_input`. The library never prompts, because it has no UI, and
never guesses, because a wrong guess is worse than an admitted gap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx2

from ..catalog.model import Catalog, ModelEntry, ModelVariant
from ..errors import ConfigError
from ..local.acquire import (
    AcquisitionReport,
    AcquisitionRequest,
    ProgressSink,
    acquire,
    launch_hints_for,
    plan_acquisition,
)
from ..local.backends import Backend, select_backend
from ..local.fit import ModelFit, classify_fit, sort_by_fit
from ..local.hardware import HardwareProfile, detect
from ..local.runtimes import install_hint
from ..local.sources.huggingface import resolve_token
from ..local.store import ModelStore, ResolvedModel
from ..local.tuning import Posture
from ..local.variants import VariantChoice, VariantPrefs, evaluate_variants

__all__ = [
    "CatalogEntryFit",
    "CatalogView",
    "HardwareSource",
    "acquire_catalog_model",
    "build_catalog_view",
    "choose_variant",
    "engine_for_provider",
    "locate_catalog_model",
]

HardwareSource = Literal["detected", "provided", "unavailable"]
"""Where the profile a catalog view was judged against came from."""

_ENGINE_FOR_PROVIDER: Mapping[str, str] = {
    "llama-cpp": "llama.cpp",
    "llamacpp": "llama.cpp",
    "llama": "llama.cpp",
    "vllm": "vllm",
}


@dataclass(frozen=True, slots=True)
class CatalogEntryFit:
    """One catalog model, judged against a machine.

    Attributes:
        model: The catalog entry.
        fit: How it fits, with reasons.
        channels: Provider ids that can serve it.
    """

    model: ModelEntry
    fit: ModelFit
    channels: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        """The model id."""
        return self.model.id

    @property
    def name(self) -> str:
        """The display name."""
        return self.model.name


@dataclass(frozen=True, slots=True)
class CatalogView:
    """A filtered, fit-annotated view of the local model catalog.

    Attributes:
        entries: Models, best-fit-first.
        hardware: The profile fits were judged against, when there was one.
        hardware_source: ``"detected"`` (probed this machine), ``"provided"`` (the caller
            supplied specs), or ``"unavailable"`` — the cue to collect a remote host's
            specs from the user and call again.
        backend: The llama.cpp runtime variant that would actually drive these, when one
            is installed.
        notes: View-level remarks, such as the runtime a machine should install.
    """

    entries: tuple[CatalogEntryFit, ...] = ()
    hardware: HardwareProfile | None = None
    hardware_source: HardwareSource = "unavailable"
    backend: Backend | None = None
    notes: tuple[str, ...] = ()

    def __len__(self) -> int:
        """How many entries the view holds."""
        return len(self.entries)

    def __iter__(self) -> Any:
        """Iterate the entries, best fit first."""
        return iter(self.entries)

    @property
    def runnable(self) -> tuple[CatalogEntryFit, ...]:
        """Only the entries this machine can plausibly run."""
        return tuple(e for e in self.entries if e.fit.runnable)


def build_catalog_view(
    catalog: Catalog | None,
    *,
    provider_id: str | None = None,
    hardware: HardwareProfile | None = None,
    best_at: str | None = None,
    posture: Posture = "balanced",
    probeable: bool = True,
    backend: Backend | None = None,
    detect_backend: bool = True,
) -> CatalogView:
    """Assemble a fit-annotated catalog view. Performs no network I/O.

    Args:
        catalog: The catalog to browse. ``None`` yields an empty view.
        provider_id: Restrict to models available on one channel.
        hardware: Specs to judge against. Supplying these marks the view ``"provided"``,
            which is how an application answers for a remote host.
        best_at: Restrict to one category from the catalog's closed vocabulary.
        posture: How much of the machine to budget.
        probeable: Whether this machine is the one that would run the model. False for a
            non-loopback engine, where probing would describe the wrong computer.
        backend: The runtime that would drive these, when the caller already selected one.
        detect_backend: Look for an installed runtime when ``backend`` was not supplied.

    Returns:
        The view, entries sorted best-fit-first.
    """
    if catalog is None:
        return CatalogView(hardware=hardware, hardware_source="unavailable")

    source: HardwareSource
    if hardware is not None:
        source = "provided"
    elif probeable:
        hardware = detect()
        source = "detected"
    else:
        source = "unavailable"

    if backend is None and detect_backend and hardware is not None:
        backend = select_backend(hardware)

    models = catalog.models_for(provider_id, best_at=best_at)
    if best_at and not models and not _known_category(catalog, best_at):
        raise ConfigError(
            f"unknown best_at category {best_at!r}",
            hint="see anyinfer.catalog.BEST_AT for the full list",
        )

    judged = [
        (entry, classify_fit(entry, hardware, posture=posture, backend=backend))
        for entry in models
    ]
    ordered = sort_by_fit(judged)

    notes: list[str] = []
    if source == "unavailable":
        notes.append(
            "this engine is not running on a machine AnyInfer can probe, so no fit could be "
            "judged; collect the host's RAM, VRAM, and accelerator and pass "
            "HardwareProfile.from_user_input(...)"
        )
    elif hardware is not None and hardware.user_supplied:
        notes.append("fits are based on specs you provided, not measured")
    if backend is None and hardware is not None:
        notes.append(install_hint(hardware))

    return CatalogView(
        entries=tuple(
            CatalogEntryFit(model=entry, fit=fit, channels=entry.channels)
            for entry, fit in ordered
        ),
        hardware=hardware,
        hardware_source=source,
        backend=backend,
        notes=tuple(notes),
    )


def _known_category(catalog: Catalog, category: str) -> bool:
    """Whether any model in the catalog carries a category tag."""
    wanted = category.strip().lower()
    return any(wanted in entry.best_at for entry in catalog.models.values())


# ---- acquisition -----------------------------------------------------------------------


def engine_for_provider(provider_id: str | None) -> str | None:
    """Map a provider id to the engine whose variants it can serve."""
    if provider_id is None:
        return None
    return _ENGINE_FOR_PROVIDER.get(provider_id.strip().lower())


def choose_variant(
    entry: ModelEntry,
    *,
    engine: str | None,
    hardware: HardwareProfile | None,
    backend: Backend | None,
    prefs: VariantPrefs | None,
    variant_id: str | None,
) -> tuple[ModelVariant, VariantChoice | None]:
    """Pick the variant to acquire, explicitly or by hardware fit.

    Raises:
        ConfigError: If nothing acceptable fits, with the ladder's rejection reasons
            attached so the answer is arguable rather than opaque.
    """
    if variant_id is not None:
        return entry.variant(variant_id), None

    candidates = entry.variants_for(engine)
    if not candidates:
        variant_engines = ", ".join(sorted({variant.engine for variant in entry.variants}))
        hint = f"downloadable variant engines: {variant_engines or '(none)'}"
        channel = getattr(entry, engine.replace("-", "_"), None) if engine else None
        tag = getattr(channel, "tag", None)
        if isinstance(tag, str) and tag:
            hint += (
                f"; this channel owns its model store, so use pull_model({engine!r}, "
                f"{tag!r}) instead"
            )
        raise ConfigError(
            f"catalog model {entry.id!r} has no downloadable weight variants for "
            f"{engine or 'any engine'}",
            hint=hint,
        )

    choice, rejections = evaluate_variants(
        candidates,
        hardware,
        engine=engine,
        parameter_size=entry.parameter_size,
        backend=backend,
        prefs=prefs,
    )
    if choice is None:
        if hardware is None:
            raise ConfigError(
                f"choosing a quantization for {entry.id!r} needs a hardware profile",
                hint=("pass hardware=..., or name a variant explicitly with variant_id="),
            )
        # The rejections are the answer to "why not?", and a refusal that withholds them
        # is one a user cannot act on.
        detail = "; ".join(f"{variant_id}: {reason}" for variant_id, reason in rejections)
        raise ConfigError(
            f"no curated quantization of {entry.id!r} fits this machine — {detail}",
            hint=(
                "choose a smaller model — below Q4_K_M a smaller model at a good "
                "quantization beats this one at a bad quantization; pass "
                "prefs=VariantPrefs(allow_low_quality=True) to override"
            ),
        )
    return entry.variant(choice.variant_id), choice


async def acquire_catalog_model(
    catalog: Catalog | None,
    store: ModelStore,
    model_id: str,
    *,
    engine: str | None = None,
    variant_id: str | None = None,
    hardware: HardwareProfile | None = None,
    progress: ProgressSink | None = None,
    prefs: VariantPrefs | None = None,
    dry_run: bool = False,
    token: str | None = None,
    client: httpx2.AsyncClient | None = None,
    enforce_license: bool = True,
    allow_unverified: bool = False,
    max_concurrent_files: int = 3,
) -> AcquisitionReport:
    """Choose a variant of a catalog model and acquire it into the store.

    ``dry_run=True`` resolves and reports the exact byte count without writing anything —
    what an application needs to put a real confirmation dialog in front of a
    forty-gigabyte download.

    Raises:
        ConfigError: If there is no catalog, the model is unknown, or no variant fits.
        LocalRuntimeError: On a transfer failure, a digest mismatch, or insufficient disk.
    """
    if catalog is None:
        raise ConfigError(
            "acquiring a model needs a catalog",
            hint="build the client with the bundled catalog, or pass catalog=...",
        )
    entry = catalog.model(model_id)
    if hardware is None and variant_id is None:
        hardware = detect()
    backend = select_backend(hardware) if hardware is not None else None

    variant, choice = choose_variant(
        entry,
        engine=engine,
        hardware=hardware,
        backend=backend,
        prefs=prefs,
        variant_id=variant_id,
    )

    request = AcquisitionRequest(
        ref=variant.source,
        model_id=entry.id,
        variant_id=variant.id,
        kind=variant.kind,
        engine=variant.engine,
        quantization=variant.quantization,
        license=entry.license,
        token=resolve_token(token),
        max_concurrent_files=max_concurrent_files,
        allow_unverified=allow_unverified,
        enforce_license=enforce_license,
    )

    plan = await plan_acquisition(request, store=store, client=client)
    report = await acquire(
        request,
        store=store,
        client=client,
        progress=progress,
        plan=plan,
        dry_run=dry_run,
    )
    if choice is not None:
        return _with_reasons(report, choice)
    return report


def _with_reasons(report: AcquisitionReport, choice: VariantChoice) -> AcquisitionReport:
    """Attach the variant-selection rationale to a report's warnings.

    Selection reasons are not warnings in the "something went wrong" sense, but they are
    exactly what a user asking "why this quantization?" needs, and a report is where they
    will look.
    """
    return replace(report, warnings=(*report.warnings, *choice.reasons))


def locate_catalog_model(
    catalog: Catalog | None,
    store: ModelStore,
    model_id: str,
    *,
    variant_id: str | None = None,
    engine: str | None = None,
    verify: bool = False,
    hardware: HardwareProfile | None = None,
    context_size: int | None = None,
) -> ResolvedModel | None:
    """Find an already-acquired model and describe how to launch an engine against it.

    No network I/O. The returned `ResolvedModel.launch_hints` are advisory data: this
    locates weights and computes arguments, it does not start anything.
    """
    entry = store.find(model_id, variant_id=variant_id, engine=engine)
    if entry is None:
        return None

    window = context_size
    gpu_layers: int | None = None
    if catalog is not None and entry.model_id in catalog.models:
        window = window or catalog.model(entry.model_id).context_window
    if hardware is not None:
        gpu_layers = 99 if hardware.has_accelerator else 0

    hints = launch_hints_for(
        entry,
        path=store.root / entry.handle,
        context_size=window,
        gpu_layers=gpu_layers,
    )
    return store.locate(
        model_id,
        variant_id=variant_id,
        engine=engine,
        verify=verify,
        launch_hints=hints,
    )
