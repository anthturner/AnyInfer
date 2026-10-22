# Propagating a Provider Change — Canonical Procedure

Tool-agnostic procedure for turning verified upstream provider evidence into a coordinated
change across AnyInfer's shared specification and registered implementations. Entry points:
the `propagate-provider-change` skill (Codex, Claude Code), the Copilot prompt
`.github/prompts/propagate-provider-change.prompt.md`, or any agent following this file.

Read [AGENTS.md](../AGENTS.md), [DRIFT-CHECK.md](DRIFT-CHECK.md),
[NEW-PROVIDER.md](NEW-PROVIDER.md), and [specification/MAINTENANCE.md](../specification/MAINTENANCE.md)
before proposing implementation work. This procedure coordinates evidence and changes; it
does not replace the provider contract research procedure or the immutable specification
release rules.

## 1. Establish the evidence

Start from a classified finding in a provider drift report or from a newly researched
provider contract. For every material assertion, preserve the provider-owned source URL,
the date it was fetched, the version or release pin when applicable, and the exact observed
change. Record inaccessible, ambiguous, or conflicting evidence as unresolved. Never fill a
gap from memory or from a neighboring provider.

Classify the disposition as adopted, informational, unverifiable, or blocked. A drift,
deprecation, or new capability is evidence to assess, not an automatic requirement. Adopt a
change only when the evidence and product behavior justify it. A newly advertised upstream
capability remains informational unless separately reviewed and adopted. State what was
adopted, what remains informational, and why.

## 2. Choose the behavior path

Determine whether the change affects AnyInfer's normalized behavior or only the wire
translation.

- **Shared behavior change:** If a user-visible normalized result, invariant, or supported
  capability changes, propose the normative update at new specification paths and follow
  `specification/MAINTENANCE.md` for a candidate profile/release and cases. Keep all existing
  frozen release assets byte-for-byte unchanged. A draft preparation may propose new
  normative/schema/input assets, but it cannot create qualified release evidence or claim a
  candidate is qualified.
- **Wire-only change:** If protocol translation changes while normalized behavior remains
  the same, record the explicit rationale that there is no shared-spec delta. Update the
  relevant provider snapshot, affected adapters, and transport tests. Do not create a
  specification release solely to record a wire translation.

If the evidence cannot establish which path applies, leave the work blocked or informational
with the missing evidence named. Do not resolve uncertainty by broadening the specification.

## 3. Account for affected implementations

Use the registered implementation inventory and the actual provider/operation bindings to
identify the dependency closure. A changed provider or preset snapshot can affect inherited
base dialects and shared adapters; include every such dependency. For example, an OpenAI
compatible preset change may affect both its preset record and the shared OpenAI dialect.
Use actual registration and adapter composition, not labels or hand-maintained assumptions.

For each registered implementation, account for every affected binding and the required
verification gates. Mark a binding unaffected only with a reviewed rationale. Mark it
unsupported only when that binding is actually absent. A missing dependency mapping or
unclear inventory blocks a complete impact claim. Shared-core or shared-specification impact
still requires each applicable implementation/profile gate even when that implementation
has no binding for the provider. Record future languages through the same registration
contract; do not imply support from a language's planned status. MCP and Hugging Face
snapshots are non-inference dependencies: route them to an explicit out-of-binding-scope or
blocked disposition rather than inventing inference operations.

The change declaration is immutable input: it captures sources, decisions, affected paths,
and required work, but does not claim that work ran or passed. Generated inventories,
verification results, logs, and aggregate reports are separate run outcomes. Completion is
derived from those outcomes and trusted source/run identity, never from declaration text or
rationale prose. Use the versioned [change schema](../maintenance/change.schema.json) and
[implementation registry](../maintenance/implementations.json) as the field and gate
authority. The [registered runner](../scripts/run_provider_change_checks.py) dispatches
only registry commands; the [pure checker](../scripts/check_provider_change.py) validates
artifacts without executing commands. The controlled CI handoff is defined in
[ci.yml](../.github/workflows/ci.yml).

## 4. Prepare and verify the coordinated change

Keep changes within the registered source and candidate paths. A proposal may update the
contract snapshot, an adopted specification candidate when required, affected implementation
code, tests, and the structured impact declaration. Do not add gratuitous duplicate edits
when one shared file is consumed by multiple languages; record the shared path and require
each consumer's own applicable verification.

The registered command runner is the only command dispatcher and reads executable argv and
gate identifiers from the implementation registry. The impact checker is a pure validator
and planner: it validates declared inputs and independently produced artifacts but executes
no commands. Never accept a command from a change declaration. The complete aggregate must
require every applicable producer and gate artifact from the same CI workflow run, including
the Python gates, native C# gates, and the existing Python suite leg when suite evidence is
required. The aggregate is required by `ci-ok` whenever applicable; a skipped-job allowance
must not make it optional.

Keep source identities distinct: trusted pull-request head identity is recorded separately
from the actual evaluated checkout commit and tree. All artifacts must agree on the run,
input and registry identities, and the trusted expected source context. Missing, stale,
failed, incomplete, or mismatched evidence leaves the change blocked or draft. A dirty
preparation record is not qualified evidence.

## 5. Candidate qualification and review

For a shared-behavior candidate, follow the exact clean sequence in
`specification/MAINTENANCE.md`: commit the implementation, driver, normative text, and input
assets at revision A; produce real clean reference/environment evidence; generate candidate
release assets at revision B; run the complete Python corpus and every claiming native
report with zero failures; then obtain independent review. A `draft_prepared` change may
prepare proposed new-path assets but cannot generate a qualified release manifest or
reference expectations. Only the separate `qualified_candidate` path can follow the full
sequence. Never rewrite old release assets, silently regenerate expectations, seal, tag, or
publish automatically. Proposal and declaration status cannot claim qualification or
completion.

The manual CI candidate handoff accepts an evidence bundle from a prior run, candidate
assets checked out at the workflow root, and operator-supplied expected qualification facts
as separate inputs. The evidence path is relative to the downloaded bundle root; generated
reports stay under the workflow's temporary output wrapper. See the [dispatch inputs and
aggregation](../.github/workflows/ci.yml) and the [candidate evidence schema](../maintenance/candidate-evidence.schema.json)
for the current interface. An automated proposal remains an unqualified draft; fresh trusted
publishing validation checks the submitted facts and artifacts before any write.

Before opening a pull request, review the changed paths against the evidence, dependency
closure, frozen release assets, and required gates. Prepare one coordinated **draft** pull
request against `develop` containing the snapshot, adopted candidate basis when applicable,
affected language changes and tests, and structured impact record. Never auto-merge. Keep
incomplete or failed work draft or blocked, and do not open a pull request for a no-change
result with no adopted or otherwise meaningful work.

## 6. Preserve control-plane integrity

The proposal cannot weaken the validators, CI workflow, implementation registry, or frozen
asset safeguards that evaluate it. A change requiring new workflow, validator, or registry
policy is blocked for separate review; it cannot approve its own bypass. Preserve the
existing authenticated CI action, backend, secrets, and cost posture. Do not add a new model,
backend, or credential requirement as part of propagation.

Report adopted and informational findings, the shared-spec or wire-only rationale, affected
and missing bindings, each required gate and its actual result, and any unresolved blockers.
Use draft or blocked status until same-run evidence and independent review support the
claimed outcome.
