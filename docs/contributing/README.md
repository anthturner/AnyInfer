# Contributing

Security vulnerabilities do not belong in public issues. Follow the repository's
[security policy](https://github.com/anthturner/AnyInfer/security/policy) for private
reporting.

## Setup

```bash
git clone <repo> && cd AnyInfer
python -m venv .venv && . .venv/bin/activate       # or .venv\Scripts\activate
python workspace.py setup                          # installs the project and dev extras
python workspace.py check                          # every gate CI runs
```

Python 3.11+. Windows, macOS, and Linux are all first-class and all tested in CI.

## The Task Runner

[`workspace.py`](https://github.com/anthturner/AnyInfer/blob/main/workspace.py) is the one
entry point for routine commands: `python workspace.py <verb>` in a fresh clone,
`workspace <verb>` once installed, or the checked-in `./workspace` (sh) and
`workspace.cmd` (Windows) wrappers from the repo root. Run it with no arguments to list
every verb.

| Verb | Does |
|---|---|
| `python workspace.py setup` | Install the project and all dev extras, editable |
| `python workspace.py check` | Run the quality gates as ordered phases; `--skip=`/`--only=` select phases, `--fix` lets ruff rewrite |
| `python workspace.py demo` | Launch the [pack-in demo app](../guides/demo-app.md) |
| `python workspace.py serve` | Run the OpenAI-compatible sidecar |
| `python workspace.py build [wheel\|demo\|serve\|docs\|all] [platform]` | Build packages, native bundles, and/or the docs site |
| `python workspace.py clean` | Remove build artifacts and caches |
| `python workspace.py docs` | Serve the docs site locally with live reload |
| `python workspace.py web` | Build and serve the exact artifact Pages will publish |
| `python workspace.py doctor` / `providers` | Hardware report; registered providers |

Every third-party gate shells out to the same command CI runs and echoes it first, so the
runner is a convenience rather than a second source of truth; you can always copy the
printed line. First-party maintenance code (the docstring-coverage gate, the doc-link
check, the conformance-matrix generator, the demo-bundle build) lives in `workspace.py`
itself rather than a scripts directory, so every dev and devops task is in one file with
one `--help`.

## The Quality Gates

`python workspace.py check` runs the gates as named, ordered phases (fastest feedback
first), and every phase runs in CI and must pass. It keeps going after a failure so one invocation
tells you everything that is broken:

| Phase | Runs |
|---|---|
| `lint` | `ruff check src tests workspace.py` (`--fix` applies fixes) |
| `types` | `mypy` (strict) |
| `contracts` | `lint-imports`: the architecture contracts |
| `changelog` | `scripts/validate_changelog.py`: [changelog](changelog.md) shape, and that released sections have not been rewritten |
| `test` | `pytest -q`, the full suite, headless |
| `conformance` | The provider [conformance suite](conformance.md) and the serve invariants |
| `docs-check` | Docstring coverage, doc links, and the runnable doc examples |
| `docs-build` | `mkdocs build --strict`: the exact artifact the Pages deploy publishes |

That table is the whole pipeline: every step of every CI job is one of these phases,
invoked as `python workspace.py check --only=<phase>`. A green `check` therefore means what
a green CI run means, with one exception: CI also runs the `test` phase across
Python 3.11–3.14 on Linux, Windows, and macOS, which only the runners can cover.

`--skip=a,b` leaves phases out; `--only=a,b` runs just those; the two are mutually
exclusive. `python workspace.py build docs` runs the same strict site build as the
`docs-build` phase, for when you want the artifact rather than the verdict.

The formatter is not a default gate, since it reflows argv-style flag/value pairs into a
less readable shape; `python workspace.py check --only=format --fix` formats anyway.

`lint-imports` is the unusual one: it enforces the architecture boundaries mechanically
rather than relying only on review. The contracts and what each one forbids are listed in
[architecture](architecture.md#enforcement); when one fails, the fix is almost always to
move code, not to loosen the contract.

## Where to Read First

1. [DESIGN.md](https://github.com/anthturner/AnyInfer/blob/main/DESIGN.md): architecture and decision rationale. Start with §3 and §23.
2. [Architecture](architecture.md): the condensed version of the rules.

## Choose the Owning Workstream

Core engine, shared configuration, CLI, sidecar, and demo code have separate ownership
boundaries. The [coding-agent instructions](automation.md) page maps each workstream to its
paths and explains the canonical-instructions model the tool-specific files defer to. The
same boundaries apply whether the contributor is using an agent or editing by hand.

## The One Rule

> **Adapters only translate. The core orchestrates.**

If you are adding control flow to an adapter — a retry, a validation step, a fallback — stop.
It belongs in the core, where it is implemented once and behaves identically for every
provider. That property is the product.

## Conventions

- Frozen `dataclasses` with `slots=True` for domain types; `typing.Protocol` for interfaces.
- **No pydantic dependency.** Caller-supplied pydantic models are accepted via duck-typed
  `model_json_schema()` only.
- Errors carry structured fields and an actionable `hint`. A hint that does not tell the
  user what to *do* is not a hint.
- Anything credential-shaped goes through `anyinfer.credentials` and is registered for
  redaction.
- Local servers bind `127.0.0.1` unless a caller explicitly opts out.
- New mandatory dependencies need justification. The slim core is a security property as
  much as an aesthetic one.

## Comments

Comment the *why*, not the *what*. The valuable comments in this codebase explain
non-obvious constraints:

```python
# Closing a buffered pipe while another thread is blocked reading it deadlocks, and on
# Windows a grandchild process can keep the write end open after its parent exits, so the
# stream is closed here, on the way out, and nowhere else.
```

## Pull Requests

A change touching an adapter's wire behavior includes:

- the adapter change;
- an updated [contract snapshot](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md) in the same change set;
- conformance results;
- its provider page, if behavior changed.

Run the [drift check](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md) before starting adapter work, so you are
coding against what the provider does *now*.

## Where Next

- [Writing a provider adapter](writing-an-adapter.md): the adapter contract, the
  descriptor, and the OpenAI-dialect shortcut.
- [The conformance suite](conformance.md): certifying an adapter and contributing
  cassettes.
- [Testing guide](testing.md): the fast track, the gate, and where a test belongs.
- [Branching and releases](releasing.md): the branch model and how a version bump reaches
  PyPI.
- [The changelog](changelog.md): what earns an entry, and why released sections are
  frozen.
- [Branding and visual assets](branding.md): the canonical marks and the rules for using
  them.
