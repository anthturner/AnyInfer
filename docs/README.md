# AnyInfer Documentation

AnyInfer provides a provider-independent inference runtime for Python applications, as
well as an OpenAI-compatible sidecar for everything else. This page is the table of
contents; everything else is one click away. These same pages are published, with a
generated SDK reference, at **[anyinfer.dev](https://anyinfer.dev/)**.

In a hurry? The [quickstart](guides/quickstart.md) gets you from `pip install` to a
working `generate()` call in ~5 minutes.

## Choose Your Path

The documentation is organized by what you are trying to do, not by how the code is
arranged.

| I want to… | Go to |
|---|---|
| Decide whether AnyInfer is the right layer, and see what makes it different | [Why and when to use AnyInfer](why-anyinfer.md) |
| Add AnyInfer to my application | [Integrate AnyInfer](guides/README.md) |
| Run it as a service my existing tools talk to | [OpenAI-compatible sidecar](serve/README.md) |
| Understand how it works before committing | [Concepts](concepts/README.md) |
| See a provider's setup and quirks | [Providers](providers/README.md) |
| Read complete runnable programs | [Examples](examples/README.md) |
| Look something up | [Reference](reference/README.md) |
| Write an adapter, or contribute | [Contributor guide](contributing/README.md) |

## For Integrators

Read in roughly this order:

1. [Quickstart](guides/quickstart.md): install to first result.
2. [Integrate AnyInfer](guides/README.md): Python SDK, command-line tool, or sidecar,
   and the full list of task guides (streaming, schemas, fallback, tool loop, context,
   offline testing, local models).
3. [Installation and extras](guides/installation.md): which extras you need.
4. [Shared configuration](reference/configuration.md): one file for every path.
5. [Concepts](concepts/README.md): eighteen ideas, one line each; read them once and
   the rest of the API follows.

Letting a coding agent write the integration?
[Coding agents](guides/coding-agents.md) covers `anyinfer agents-md`, `llms.txt`, and
the [integration procedure](agents/INTEGRATION.md) it can execute. The
[demo app](guides/demo-app.md) is a complete offline reference integration, with
standalone builds on the [downloads page](downloads.md).

## For Contributors

- [Contributor guide](contributing/README.md): setup, the quality gates, and what CI
  checks.
- [Architecture](contributing/architecture.md): the load-bearing rules.
- [Writing a provider adapter](contributing/writing-an-adapter.md) and
  [the conformance suite](contributing/conformance.md).
- [Provider contract snapshots](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md)
  and the
  [drift check](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md).
- [Testing](contributing/testing.md): fakes, cassettes, and what to test where.
- [Branching and releases](contributing/releasing.md).

## Design Documents

The sources of truth for *why* things are the way they are:

- [DESIGN.md](https://github.com/anthturner/AnyInfer/blob/main/DESIGN.md): architecture,
  decision rationale, open questions, and the risk register.
- [AGENTS.md](https://github.com/anthturner/AnyInfer/blob/main/AGENTS.md): canonical
  repository automation instructions.
