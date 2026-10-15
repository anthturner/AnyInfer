# AnyInfer language-neutral specifications

This directory contains versioned, language-neutral behavior contracts and their data-only
conformance corpora. Each implementation uses its own native driver. Passing a profile means
passing every mandatory case in the exact immutable release that the implementation declares.

## Profiles

- [`core-generation` v0](core-generation.md): asynchronous buffered and streaming generation,
  structured output and repair, routing, normalized results and events, errors, and the native
  adapter/driver proof contract.

## Vocabulary and verdicts

A **profile** is a bounded behavior contract. A **release** identifies an immutable set of
profile text, schemas, inventory, fixtures, and reference evidence. An **implementation** is a
native library claiming the profile. Its **driver** executes the released cases and required
native assertions, then emits a conformance report.

Each released case is reported exactly once as one of:

| Verdict | Meaning |
|---|---|
| `pass` | The native observation matches the case expectation and all required evidence is present. |
| `fail` | The implementation completed the case but its observation differs from the expectation. |
| `error` | Setup or harness failure, fatal runtime failure, skipped execution, cancellation where not expected, or missing required evidence. |
| `extension` | An explicitly extension-eligible boundary case produced the implementation's honest native outcome, and that exact feature is declared by the implementation. It is not a pass. |

A missing projection outside the admitted domain can be expected for an extension case; a harness
fault or missing required evidence is still `error`. Reports bind the release file's SHA-256,
identify their own implementation, source, driver, runtime, operating system, dependencies, and
declared extensions, and derive counts from their case records. A qualified report has complete
coverage with no `fail` or `error`; matching failures do not qualify. Python `extension` and a
native implementation's `pass` are comparable only for the same explicitly eligible case.

The exact report structure and release lifecycle are part of
[`core-generation.md`](core-generation.md) and [`MAINTENANCE.md`](MAINTENANCE.md).
