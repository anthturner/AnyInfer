# Registry, catalog, and credentials

How providers describe themselves (frozen descriptors, declarative setup specs), how
targets and aliases resolve, and how credential references become secrets. Concepts:
[targets and aliases](../../concepts/targets.md) ·
[credentials](../../concepts/credentials.md).

## Provider registry

<div class="anyinfer-api-block" markdown>

::: anyinfer.ProviderRegistry

::: anyinfer.ProviderDescriptor

::: anyinfer.ProviderSetupSpec

::: anyinfer.SetupField

::: anyinfer.HostShorthand

::: anyinfer.default_registry

::: anyinfer.providers.builtin_descriptors

</div>

## Catalog

Two shapes over one body of data: the alias ladder ("just give me a good default") and the
logical model table ("let me browse and pick"). `Catalog.with_alias_target` bridges them.
See [the model catalog](../../concepts/catalog.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.Catalog

::: anyinfer.ModelEntry

::: anyinfer.ModelVariant

::: anyinfer.OllamaChannel

::: anyinfer.BEST_AT

::: anyinfer.ModelKind

::: anyinfer.MODEL_KINDS

::: anyinfer.load_default_catalog

</div>

## Browsing the local catalog

What `Client.local_catalog()` returns: every catalog model annotated with whether it fits,
and why.

<div class="anyinfer-api-block" markdown>

::: anyinfer.CatalogView

::: anyinfer.CatalogEntryFit

</div>

## Credentials

<div class="anyinfer-api-block" markdown>

::: anyinfer.CredentialResolver

::: anyinfer.ResolverChain

::: anyinfer.default_resolver

</div>
