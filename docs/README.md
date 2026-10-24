# AnyInfer Documentation

AnyInfer is an application-owned hybrid inference runtime with a shared foundation and
independent Python and C# SDK implementations. Python remains the supported published SDK;
its CLI and OpenAI-compatible sidecar use the same engine. The native .NET 8 C# SDK is in
development as a prerelease local package and does not claim full parity. See the
[shared foundation](concepts/foundation.md) for the current capability map. This page is the
table of contents; the documentation is published at **[anyinfer.dev](https://anyinfer.dev/)**.

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
2. [Integrate AnyInfer](guides/README.md): supported Python SDK, command-line tool, or
   sidecar, plus task guides. The C# SDK in development has its own
   [guide](guides/csharp-sdk.md) and [migration map](guides/python-to-csharp.md).
3. [Installation and extras](guides/installation.md): which extras you need.
4. [Shared configuration](reference/configuration.md): one file for the Python SDK, CLI,
   and sidecar. C# reads its [documented v1 subset](guides/python-to-csharp.md).
5. [Concepts](concepts/README.md): one line each; read them once and
   the rest of the API follows.

Letting a coding agent write the integration?
[Coding agents](guides/coding-agents.md) covers `anyinfer agents-md`, `llms.txt`, and
the [integration procedure](agents/INTEGRATION.md) it can execute. The
[demo app](guides/demo-app.md) is a complete offline reference integration, with
standalone builds on the [downloads page](downloads.md).

## For Contributors

- [Contributor guide](contributing/README.md): setup, the quality gates, and what CI
  checks.
- [C# SDK development and conformance](contributing/csharp-proof.md): native .NET 8
  development workflow and frozen-contract verification. Python remains the supported
  published SDK; the C# package is prerelease and not published to NuGet. See its
  [capability map](concepts/foundation.md), [SDK guide](guides/csharp-sdk.md), and
  [reference](reference/csharp-sdk.md).
- [Architecture](contributing/architecture.md): the load-bearing rules.
- [Writing a provider adapter](contributing/writing-an-adapter.md) and
  [the conformance suite](contributing/conformance.md).
- [Provider contract snapshots](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md)
  and the
  [drift check](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md).
- [Testing](contributing/testing.md): fakes, cassettes, and what to test where.
- [Branching and releases](contributing/releasing.md) and
  [the changelog](contributing/changelog.md).

## Design Documents

The sources of truth for *why* things are the way they are:

- [DESIGN.md](https://github.com/anthturner/AnyInfer/blob/main/DESIGN.md): architecture,
  decision rationale, open questions, and the risk register.
- [AGENTS.md](https://github.com/anthturner/AnyInfer/blob/main/AGENTS.md): canonical
  repository automation instructions.
