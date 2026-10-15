"""Provider adapters: one module per protocol dialect.

Built-in descriptors are enumerated lazily by `builtin_descriptors()` so that importing
`anyinfer` does not import every adapter (and, through them, every optional dependency).
An adapter whose extra is not installed simply never loads until it is asked for.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..registry import ProviderDescriptor

__all__ = ["builtin_descriptors"]

_BUILTIN_MODULES: tuple[str, ...] = (
    "openai_compat",
    "openai",
    "anthropic",
    "gemini",
    "vertex",
    "bedrock",
    "cohere",
    "nebius",
    "deepseek",
    "xai",
    "lm_studio",
    "ollama",
    "tei",
    "voyage",
    "jina",
    "openrouter",
    "azure_foundry",
    "copilot",
    "m365_copilot",
    "llama_cpp",
)


def builtin_descriptors() -> Iterator[ProviderDescriptor]:
    """Yield every built-in provider descriptor.

    A module that fails to import — typically because its optional extra is absent — is
    skipped rather than breaking discovery for the others. The resulting "unknown provider"
    error, raised only if that provider is actually requested, carries the install hint.
    """
    import importlib

    for name in _BUILTIN_MODULES:
        try:
            module = importlib.import_module(f".{name}", __package__)
        except ImportError:
            continue
        descriptor = getattr(module, "descriptor", None)
        if isinstance(descriptor, ProviderDescriptor):
            yield descriptor

    from .presets import preset_descriptors

    yield from preset_descriptors()
