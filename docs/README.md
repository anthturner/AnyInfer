# AnyInfer documentation

**Start here.** This page is the table of contents; everything else is one click away.
These same pages are published, with a generated SDK reference, at
**[anyinfer.dev](https://anyinfer.dev/)**.

If you are in a hurry: [Quickstart](guides/quickstart.md) gets you from `pip install` to a
working `generate()` call in about five minutes.

---

## Choose your path

The documentation is organized by what you are trying to do, not by how the code is
arranged.

| I want to… | Go to |
|---|---|
| Decide whether AnyInfer is the right layer | [When to use AnyInfer](guides/when-to-use.md) |
| Add AnyInfer to my application | [Integrator guide](#for-integrators) |
| Run it as a service my existing tools talk to | [OpenAI-compatible sidecar](serve/README.md) |
| Understand how it works before committing | [Concepts](concepts/README.md) |
| Write an adapter, or contribute | [Contributor guide](contributing/README.md) |
| Look something up | [Reference](reference/README.md) |

---

## For integrators

You are embedding AnyInfer in an application.

**Getting started**

1. [When to use AnyInfer](guides/when-to-use.md) — what it replaces, and what it
   deliberately does not.
2. [Quickstart](guides/quickstart.md) — install to first result.
3. [Choosing an integration path](guides/integration-paths.md) — Python SDK, command-line
   tool, or sidecar.
4. [Installation and extras](guides/installation.md) — which extras you need, and why the
   core is deliberately small.
5. [Shared configuration](reference/configuration.md) — one file for every integration path.

**Concepts** — read these once and the rest of the API explains itself.

- [Targets and aliases](concepts/targets.md) — how `"medium"` and
  `"anthropic:claude-sonnet-4-5"` both resolve.
- [The event stream](concepts/events.md) — the one primitive everything else projects from.
- [Routing: retries, fallback, health](concepts/routing.md)
- [Structured output and repair](concepts/structured-output.md)
- [Capabilities and provenance](concepts/capabilities.md) — why every number says where it
  came from.
- [Token estimation and context budgets](concepts/budgeting.md) — fit and cost before
  dispatch.
- [Context reduction](concepts/context-reduction.md) — reduce approved material and report
  omissions.
- [Credentials and redaction](concepts/credentials.md)
- [Telemetry and observers](concepts/telemetry.md)
- [The local subsystem](concepts/local.md) — hardware detection through supervised servers.

**How-to guides** — task-shaped, copy-pasteable.

- [Stream to a terminal](guides/streaming.md)
- [Enforce a JSON schema](guides/structured-output.md)
- [Add a fallback chain](guides/fallback.md)
- [Run a model locally, end to end](guides/local-inference.md)
- [Observe requests and bridge to OpenTelemetry](guides/observability.md)
- [Store credentials in the OS keyring](guides/credentials.md)
- [Run the tool loop](guides/tool-loop.md)
- [Fit a corpus to a context budget](guides/fitting-context.md)
- [Explore the pack-in demo app](guides/demo-app.md) — a PySide6 reference integration that
  runs offline. Standalone builds are on the [downloads page](downloads.md).

**Examples** — complete programs, exercised in CI.

- [Structured summaries with a fallback chain](examples/summarize-with-fallback.md)
- [A local tool-calling assistant](examples/local-tool-agent.md)

**Providers** — one page each, with the quirks that matter.

[All providers](providers/README.md) ·
[openai](providers/openai.md) ·
[anthropic](providers/anthropic.md) ·
[ollama](providers/ollama.md) ·
[llama-cpp](providers/llama-cpp.md) ·
[copilot](providers/copilot.md) ·
[azure-foundry](providers/azure-foundry.md) ·
[openrouter](providers/openrouter.md) ·
[m365-copilot](providers/m365-copilot.md) ·
[openai-compat](providers/openai-compat.md)

---

## For contributors

You are changing AnyInfer itself, or writing an adapter for it.

- [Contributor guide](contributing/README.md) — setup, the quality gates, and what CI checks.
- [Architecture](contributing/architecture.md) — the load-bearing rules and why they exist.
- [Writing a provider adapter](contributing/writing-an-adapter.md) — including how to
  certify it against the conformance suite.
- [The conformance suite](contributing/conformance.md)
- [Provider contract snapshots](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md) and the
  [drift check](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md).
- [Testing guide](contributing/testing.md) — fakes, cassettes, and what to test where.
- [Branching and releases](contributing/releasing.md) — how a change becomes a release.

---

## Reference

- [SDK reference](reference/api/README.md) — every public symbol, generated from the
  docstrings (best read on the [published site](https://anyinfer.dev/reference/api/)).
- [Error catalog](reference/errors.md) — every exception, when it is raised, and what its
  `hint` will tell your user.
- [Conformance matrix](reference/conformance-matrix.md) — what each provider actually
  supports, generated from test results.
- [Shared configuration](reference/configuration.md) — provider settings, environment
  variables, and the common file format.
- [Glossary](reference/glossary.md)

---

## Design documents

The architecture is settled and written down. These are the sources of truth for *why*
things are the way they are:

- [DESIGN.md](https://github.com/anthturner/AnyInfer/blob/main/DESIGN.md) — architecture, module responsibilities, and decision rationale.
- [IMPLEMENTATION.md](https://github.com/anthturner/AnyInfer/blob/main/IMPLEMENTATION.md) — normative types, algorithms, and the build plan.
- [NOTES.md](https://github.com/anthturner/AnyInfer/blob/main/NOTES.md) — decisions, assumptions, open questions, risks, and the
  competitive review that shaped several behaviors.
- [AGENTS.md](https://github.com/anthturner/AnyInfer/blob/main/AGENTS.md) — canonical repository automation instructions.
