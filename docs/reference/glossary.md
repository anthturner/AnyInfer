# Glossary

Terms this project uses precisely. Where a word has a loose industry meaning and a specific
meaning here, the specific one is what the code implements.

<div class="anyinfer-card-grid" markdown>

<div class="anyinfer-card" markdown>
#### Adapter { #adapter }
The per-provider module that translates a `WireRequest` into a provider's wire format and
its responses back into events. Adapters *only* translate; they never retry, validate, or
measure.
</div>

<div class="anyinfer-card" markdown>
#### Alias { #alias }
A tier name (`small`, `medium`, `large`) that resolves to a concrete model per provider
through the catalog.
</div>

<div class="anyinfer-card" markdown>
#### Attempt { #attempt }
One try against one resolved target. A request may involve several, across retries and
fallback; the full trail is on every result.
</div>

<div class="anyinfer-card" markdown>
#### Capability { #capability }
Something a model can do, paired with the provenance of how we know.
</div>

<div class="anyinfer-card" markdown>
#### Cassette { #cassette }
Recorded HTTP traffic replayed in tests, so conformance can run without credentials.
</div>

<div class="anyinfer-card" markdown>
#### Catalog { #catalog }
The data file mapping aliases to per-provider targets, and artifact ids to pinned,
hash-verified downloads.
</div>

<div class="anyinfer-card" markdown>
#### Conformance suite { #conformance-suite }
The shared test suite every adapter must pass. It proves *our code matches our claims*; the
drift check proves *our claims still match upstream*.
</div>

<div class="anyinfer-card" markdown>
#### Descriptor { #descriptor }
Frozen, declarative data about a provider: how to build its adapter, what configuration it
needs, how it spells reasoning effort, what it supports.
</div>

<div class="anyinfer-card" markdown>
#### Drift check { #drift-check }
The semi-automated audit comparing contract snapshots against providers' current public
documentation.
</div>

<div class="anyinfer-card" markdown>
#### Event stream { #event-stream }
The generation primitive. A generation *is* an ordered stream of typed events; the
non-streaming API drains it.
</div>

<div class="anyinfer-card" markdown>
#### Fallback { #fallback }
Moving to the next target in a route after the current one fails.
</div>

<div class="anyinfer-card" markdown>
#### Health gate { #health-gate }
Skipping a target that recently failed, for a short TTL, so one dead endpoint does not cost
every request its full timeout.
</div>

<div class="anyinfer-card" markdown>
#### Mechanism { #mechanism }
How structured output was requested: `grammar`, `json_schema`, `json_mode`, or `prompt`.
Recorded on every result.
</div>

<div class="anyinfer-card" markdown>
#### Posture { #posture }
How much of a machine local inference may commit: `conservative`, `balanced`, or
`aggressive`.
</div>

<div class="anyinfer-card" markdown>
#### Projection { #projection }
Rewriting a schema for a provider's wire format (stripping keywords a grammar compiler
cannot handle efficiently). Never changes what is validated client-side.
</div>

<div class="anyinfer-card" markdown>
#### Provenance { #provenance }
Where a capability value came from: `default`, `catalog`, `discovered`, `probed`, or
`override`. Weakest to strongest — an application's deliberate `override` outranks
everything the library collected.
</div>

<div class="anyinfer-card" markdown>
#### Repair { #repair }
Re-prompting the *same* model with validation errors after a schema violation, within a
bounded budget.
</div>

<div class="anyinfer-card" markdown>
#### Route { #route }
An ordered list of targets plus policy: retries, health gating, and failure-class-specific
chains.
</div>

<div class="anyinfer-card" markdown>
#### Sentinel model { #sentinel-model }
A model id meaning "the provider chooses" (Copilot's `auto`). Capabilities for one are the
conjunction across every candidate.
</div>

<div class="anyinfer-card" markdown>
#### Sidecar { #serve-frontend }
The OpenAI-compatible HTTP service. A wire codec around a normal client, never a second
core.
</div>

<div class="anyinfer-card" markdown>
#### Target { #target }
Where a request goes: an alias, or `provider:model`.
</div>

<div class="anyinfer-card" markdown>
#### TTFT { #ttft }
Time to first token, measured by the core at the first content event, identically for every
provider.
</div>

<div class="anyinfer-card" markdown>
#### Wire request { #wire-request }
A fully-resolved request handed to an adapter: concrete model, chosen mechanism, projected
schema, translated reasoning effort, merged options.
</div>

</div>
