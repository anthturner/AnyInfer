---
kind: review
title: Language-neutral foundation planning readiness
---

> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# Planning readiness review

**Reviewed:** 2026-10-15. **Source HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Scope:** remaining material planning gaps; document/source review only, no new
runtime observations, implementation, or fixtures. The user subsequently requested
incorporating the three deliverables into the master plan as future work. This does
not approve implementation or settle reference policy, pins, or release choices.

The technical direction is documented sufficiently to stop broad architectural
brainstorming. At review time, two missing execution deliverables and one existing
open decision required explicit follow-up. The
[foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md) still owns execution
status; this review does not change its checklist or resume point.

## Findings at review time and minimum additions

| Priority / finding | Why it matters | Smallest useful plan addition | Required by |
|---|---|---|---|
| High — private O1 capture lacks an explicit implementation tranche. | P3 describes fixtures and a driver over current seams; P4 describes separate public accounting. Neither explicitly owns implementing and verifying the private core hooks required for actual selected-feedback evidence. A driver could otherwise substitute HTTP bodies or final exceptions for missing internal evidence. | Add a separately authorized O1 implementation/verification step to P3, before any baseline case claims mandatory exact-feedback coverage. Reuse the private capture design's owned paths and controlled non-racing compatibility/failure gates. Make its distinction from public accounting explicit. | Before claiming actual-feedback baseline conformance. A prototype first needs a bounded implementation brief; full streaming coverage remains separately gated. |
| High — the reference-environment binding lacks an assigned artifact and driver gate. | The I1 domain already requires pinned resources/defaults/policies, but P2/P3 do not assign a reproducible manifest plus executable preflight. Dependency/resource drift could be mistaken for a language-port defect. | Assign a versioned reference manifest and verification step: source revision, interpreter, package/resource identities, validator/default configuration, and declared warning policy. Require exact comparisons to block when required bindings mismatch or are unavailable. Keep development observations distinct from reference results. | Before reference fixture freeze and Python/C# parity claims. Capture prototypes may use a declared development environment without claiming a frozen reference. |
| Medium — D6 upstream-change management needs a concrete deliverable. | Publishing/ownership/support policy is already an open decision. Its current placeholder does not yet explain how Python, C#, and later Java stay tied to the same reference as behavior changes. | Extend the existing D6/P2.1 deliverable with immutable spec/corpus/environment identity, compatible versus breaking change rules, re-baselining requirements, implementation-supported revision declarations, and the required change checks. Resolve ownership/support-window choices there rather than inventing another architecture track. | Before publishing upstream assets or supporting independent releases; it need not block a private capture prototype. |

These recommendations assign missing work; they do not select release versions,
package pins, warning policy, public APIs, or new Python behavior. In particular,
the current broad production dependency ranges need not become the harness's
reference-environment contract, and the harness's pins need not narrow production
support.

## Existing open work, rather than new missing topics

- **W1 remains open.** Preserve both predeclared native warning-policy controls.
  Neither this review nor a reference manifest chooses the portable null-metadata
  expectation. The affected profile freeze remains blocked.
- Numeric/Unicode encoding, exact domain approval, capture limits/occurrence
  association/sealing, and portable error mappings already have named gates. Close
  the subset needed for the next bounded tranche; do not silently mark them settled.
- Accounting observation/provenance, handles, commit semantics, and pricing are
  already assigned to D3/D5/D8 and P4. Private O1 capture does not implement those
  records or close their evidence gaps.
- P3.G already provides a baseline gate and P5.1 provides a C# proceed/narrow/stop
  decision. A new general stop/go framework or a Java implementation plan is not
  needed now.

The master now assigns the three deliverables above as unchecked future work.
Each tranche must close its applicable gates under separate authorization. The
integration below records that assignment; it is not an implementation or baseline pass.

## Planning integration

| Review finding | Master-plan assignment |
|---|---|
| Explicit private O1 milestone | P3.0B bounded brief, P3.0H private hooks, and P3.0G controlled native verification. A separately authorized development prototype can precede the full profile freeze; mandatory baseline claims require capture verification for the scope claimed. Public accounting remains P4. |
| Reproducible reference artifact and gate | P2.1R defines the manifest contract; P3.1R materializes the actual source/environment binding; P3.3R implements driver preflight; P3.G requires the applicable gates. Draft fixture authoring is distinct from reference freeze, avoiding a frozen-corpus/capture dependency cycle. |
| Concrete upstream maintenance deliverable | D6/P2.1/P2.1U assign the policy, release identity, rebaselining, and implementation-support declarations. Section 6 names future staging paths. Frozen upstream identity stays separate from later implementation release/report declarations. |

All added execution/verification boxes remain unchecked, with P2.1 the next
unchecked normative item. W1 remains open and blocks the affected portable freeze;
neither a manifest nor a successful native policy control selects its expectation.
Reference pins, encoding, ownership/support windows, and release labels remain
decisions for their existing gates. Only planning Markdown was changed.

Cold review of the integration found no blocker. One wording ambiguity was
corrected: P2.1 records unresolved publishing/ownership choices, while D6 still
requires their resolution before publication. Review also checked the development
prototype exception, reference/corpus dependency order, source identity, W1,
private/public accounting separation, and immutable upstream versus implementation
support declarations. This is a planning review, not execution of the new gates.

## Review basis and limits

The cold review checked the master P2/P3/P4 sequencing, private capture §1/§8,
I1 reference-environment requirements, schema admission gates, and D6 ownership.
The coordinator also checked the current checkout and production dependency ranges
in `pyproject.toml` (`httpx2>=2.0`, `jsonschema>=4.21`). Those ranges do not define an
immutable oracle. No baseline or accounting conformance pass follows from this
document review.

Rule owners and supporting context:
[private capture design](ANYINFER_PRIVATE_CAPTURE_DESIGN.md),
[I1 domain/reporting](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md),
[I1 helper evidence](ANYINFER_I1_EVIDENCE_AUDIT.md),
[schema admission](ANYINFER_SCHEMA_ADMISSION_DRAFT.md), and
[accounting lifecycle](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md).

## Consolidation review — 2026-10-15

The active plan was consolidated around Python as the current implementation,
Python+C# as the next desired state, and equivalent native ports in arbitrary
additional languages as the future. Java and JavaScript/TypeScript on Node.js are
examples rather than an ordered or exhaustive commitment.

The master now owns all current decisions, execution, and scoped readiness. Completed
planning history and superseded walkthroughs are supporting records under evidence.
The handoff rule requires consistent active documents, closed applicable decisions,
exact checks, and a cold review before a tranche is called ready. It does not claim
that the portable profile is frozen or the private capture seam is implemented.

The cold review found no blocker. One clarification was applied: the feedback
comparison uses the original ordered schema snapshot, rather than an ambiguous
"canonical schema" that could authorize key sorting and change error selection.
Review also checked the selected policies, W1's open status, Python retry/repair and
legacy ledger/event/manifest constraints, O1/P4 separation, future-port admission,
native environment/evidence mappings, and immutable upstream release identity.

The cleanup preserves the audited Python facts and their limits. It adds no runtime
observations, implementation, fixtures, release labels, or new warning policy.
