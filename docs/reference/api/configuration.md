# Configuration API

The versioned JSON loader and what it produces: `load_config` and `loads_config` parse
and validate a file into an `AnyInferConfig`, and `dump_config` and `dumps_config` write
the same format back. The prose reference for the file format lives in
[Shared configuration](../configuration.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.CONFIG_FORMAT_VERSION

::: anyinfer.MAX_CONFIG_BYTES

::: anyinfer.AnyInferConfig

::: anyinfer.load_config

::: anyinfer.loads_config

::: anyinfer.dumps_config

::: anyinfer.dump_config

::: anyinfer.config.COMMENT_KEY

</div>

## Telemetry Sinks From Configuration

An `observers` block names sinks; it does not build them. Loading a configuration file has
no side effects, so nothing opens a log file until a frontend decides to observe. See
[the `observers` block](../configuration.md#the-observers-block) for the file format and
[observability](../../guides/observability.md#a-jsonl-trail) for what to do with them.

<div class="anyinfer-api-block" markdown>

::: anyinfer.config.ObserverSpec

::: anyinfer.config.build_observers

::: anyinfer.config.BUILTIN_OBSERVERS

</div>

## Plugin Entry Points

Two entry-point groups exist so a *configuration file* can name an extension that no
constructor call could reach — which is the sidecar's only route to one. Discovery never
raises: a broken third-party package is recorded as a `PluginLoadIssue` and skipped, the
same discipline `anyinfer.registry.ProviderRegistry` applies to provider plugins.

Credential-store plugins carry a trust delta worth reading before publishing one; see
[custom schemes the sidecar can reach](../../concepts/credentials.md#custom-schemes-the-sidecar-can-reach).

<div class="anyinfer-api-block" markdown>

::: anyinfer.plugins.OBSERVER_GROUP

::: anyinfer.plugins.CREDENTIAL_STORE_GROUP

::: anyinfer.plugins.load_observers

::: anyinfer.plugins.load_credential_stores

</div>
