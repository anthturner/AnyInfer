# Glossary

Terms this project uses precisely. Where a word has a loose industry meaning and a specific
meaning here, the specific one is what the code implements.

<div class="anyinfer-card-grid" markdown>

<div class="anyinfer-card" markdown>
#### Adapter { #adapter }
The per-provider module that translates a `WireRequest` into a provider's wire format and
its responses back into events. Adapters only translate; the boundary is explained in
[writing a provider adapter](../contributing/writing-an-adapter.md).
</div>

<div class="anyinfer-card" markdown>
#### Alias { #alias }
A tier name (`small`, `medium`, `large`) that resolves to a concrete model per provider
through the catalog; see [targets and aliases](../concepts/targets.md#aliases).
</div>

<div class="anyinfer-card" markdown>
#### Arena { #arena }
Running one request against several targets at once and picking a winner by a declared
strategy, rather than falling back only on failure; see [arena](../concepts/arena.md).
</div>

<div class="anyinfer-card" markdown>
#### Attempt { #attempt }
One try against one resolved target. A request may involve several, across retries and
fallback; the full [attempt trail](../concepts/routing.md#the-attempt-trail) is on every
result.
</div>

<div class="anyinfer-card" markdown>
#### Capability { #capability }
Something a model can do, paired with the provenance of how that is known; see
[capabilities and provenance](../concepts/capabilities.md).
</div>

<div class="anyinfer-card" markdown>
#### Cassette { #cassette }
Recorded HTTP traffic replayed in tests, so conformance can run without credentials;
[recording one](../contributing/conformance.md#contributing-a-cassette) takes a single
command.
</div>

<div class="anyinfer-card" markdown>
#### Catalog { #catalog }
The data file mapping aliases to per-provider targets, and artifact ids to pinned,
hash-verified downloads; see [the model catalog](../concepts/catalog.md).
</div>

<div class="anyinfer-card" markdown>
#### Confidentiality Tier { #confidentiality-tier }
One of five numbered postures (0-4) for protecting prompt IP, each stating its own
guarantee *and* its ceiling; see
[confidentiality tiers](../guides/confidentiality-tiers.md).
</div>

<div class="anyinfer-card" markdown>
#### Conformance Suite { #conformance-suite }
The shared test suite every adapter must pass before its matrix row is published; see
[the conformance suite](../contributing/conformance.md).
</div>

<div class="anyinfer-card" markdown>
#### Descriptor { #descriptor }
Frozen, declarative data about a provider: how to build its adapter, what configuration it
needs, how it spells reasoning effort, what it supports. See
[start from a descriptor](../contributing/writing-an-adapter.md#start-from-a-descriptor).
</div>

<div class="anyinfer-card" markdown>
#### Drift Check { #drift-check }
The semi-automated audit comparing contract snapshots against providers' current public
documentation, following
[`contracts/DRIFT-CHECK.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md).
</div>

<div class="anyinfer-card" markdown>
#### Event Stream { #event-stream }
The generation primitive. A generation *is* an ordered stream of typed events, described
in [the event stream](../concepts/events.md); the non-streaming API drains it.
</div>

<div class="anyinfer-card" markdown>
#### Extra { #extra }
An optional install group (`anyinfer[serve]`, `[otel]`, `[demo]`) naming a capability
rather than a provider, so the core install stays two dependencies wide. The full table
is in [installation](../guides/installation.md#extras).
</div>

<div class="anyinfer-card" markdown>
#### Fallback { #fallback }
Moving to the next target in a [route](../concepts/routing.md) after the current one
fails.
</div>

<div class="anyinfer-card" markdown>
#### Health Gate { #health-gate }
Skipping a target that recently failed, for a short TTL, so one dead endpoint does not cost
every request its full timeout; see
[health gating](../concepts/routing.md#health-gating).
</div>

<div class="anyinfer-card" markdown>
#### Mechanism { #mechanism }
How [structured output](../concepts/structured-output.md) was requested: `grammar`,
`json_schema`, `json_mode`, or `prompt`. Recorded on every result.
</div>

<div class="anyinfer-card" markdown>
#### Posture { #posture }
How much of a machine [local inference](../concepts/local.md) may commit:
`conservative`, `balanced`, or `aggressive`.
</div>

<div class="anyinfer-card" markdown>
#### Preset { #preset }
A named configuration of the shared `openai_compat` adapter for one OpenAI-compatible
service — a registry entry, not a dedicated adapter; see
[presets](../providers/presets.md).
</div>

<div class="anyinfer-card" markdown>
#### Projection { #projection }
Rewriting a schema for a provider's wire format (stripping keywords a grammar compiler
cannot handle efficiently). Never changes what
[validation](../concepts/structured-output.md) checks client-side.
</div>

<div class="anyinfer-card" markdown>
#### Provenance { #provenance }
Where a capability value came from: `default`, `catalog`, `discovered`, `probed`, or
`override`, [weakest to strongest](../concepts/capabilities.md#the-five-provenances); an
application's `override` outranks everything the library collected.
</div>

<div class="anyinfer-card" markdown>
#### Reduction { #reduction }
Selecting and packing a caller-approved corpus down to a token budget before dispatch,
with the application deciding what may be sent; see
[context reduction](../concepts/context-reduction.md).
</div>

<div class="anyinfer-card" markdown>
#### Repair { #repair }
Re-prompting the *same* model with validation errors after a schema violation, within a
bounded budget; see [repair](../concepts/structured-output.md#repair).
</div>

<div class="anyinfer-card" markdown>
#### Route { #route }
An ordered list of targets plus policy: retries, health gating, and
failure-class-specific chains. See [routing and rate limits](../concepts/routing.md).
</div>

<div class="anyinfer-card" markdown>
#### Run Manifest { #run-manifest }
The record of what one call actually did — targets attempted, mechanism chosen, spend,
timings — available even when the call failed; see
[run manifests](../concepts/run-manifests.md).
</div>

<div class="anyinfer-card" markdown>
#### Sentinel Model { #sentinel-model }
A model id meaning "the provider chooses" (Copilot's `auto`). Capabilities for one are
[the conjunction](../concepts/capabilities.md#the-auto-sentinel) across every candidate.
</div>

<div class="anyinfer-card" markdown>
#### Session { #session }
An opaque, target-bound handle that lets capable providers reuse server-side state
across calls. It never changes an answer, and reuse is reported rather than assumed;
see [sessions](../concepts/sessions.md).
</div>

<div class="anyinfer-card" markdown>
#### Sidecar { #serve-frontend }
The OpenAI-compatible HTTP service, [`anyinfer serve`](../serve/README.md). A wire codec
around a normal client, never a second core.
</div>

<div class="anyinfer-card" markdown>
#### Target { #target }
Where a request goes: an [alias, or `provider:model`](../concepts/targets.md).
</div>

<div class="anyinfer-card" markdown>
#### TTFT { #ttft }
Time to first token,
[measured by the core](../concepts/events.md#timing-is-measured-by-the-core) at the first
content event, identically for every provider.
</div>

<div class="anyinfer-card" markdown>
#### Wire Request { #wire-request }
A fully-resolved request handed to an adapter: concrete model, chosen mechanism, projected
schema, translated reasoning effort, merged options. See
[the adapter contract](../contributing/writing-an-adapter.md#the-contract).
</div>

</div>
