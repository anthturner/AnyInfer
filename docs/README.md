# AnyInfer Documentation

AnyInfer is an application-owned hybrid inference runtime with a shared foundation and
independent Python and C# SDK implementations. Python remains the supported published SDK;
its CLI and OpenAI-compatible sidecar use the same engine. The native .NET 8 C# SDK is an
independent prerelease, locally packaged as `0.1.0-proof`, with no runtime Python dependency.
It is not published to NuGet and does not claim full parity. See the [shared foundation](concepts/foundation.md)
for the current capability map. This page is the table of contents; the documentation is
published at **[anyinfer.dev](https://anyinfer.dev/)**.

Choose the [Python quickstart](guides/quickstart.md), [Python SDK guide](guides/python-sdk.md),
or [Python reference](reference/api/README.md) for the supported published SDK. For the native
prerelease, start with the [C# SDK guide](guides/csharp-sdk.md),
[C# reference](reference/csharp-sdk.md), and
[Python-to-C# migration map](guides/python-to-csharp.md). C# is independent native .NET 8,
not a client for the Python sidecar.

## Choose Your Path

The documentation is organized by what you are trying to do, not by how the code is
arranged.

| I want to… | Go to |
|---|---|
| Decide whether AnyInfer is the right layer, and see what makes it different | [Why and when to use AnyInfer](why-anyinfer.md) |
| Add a Python application | [Python SDK guide](guides/python-sdk.md) and [installation](guides/installation.md) |
| Add a native .NET application | [C# SDK guide](guides/csharp-sdk.md), [reference](reference/csharp-sdk.md), and [migration map](guides/python-to-csharp.md) |
| Compare SDK, sidecar, and CLI integration paths | [Integrate AnyInfer](guides/README.md) |
| Run it as a service my existing tools talk to | [OpenAI-compatible sidecar](serve/README.md) |
| Understand how it works before committing | [Concepts](concepts/README.md) |
| See a provider's setup and quirks | [Providers](providers/README.md) |
| Read complete runnable programs | [Examples](examples/README.md) |
| Look something up | [Reference](reference/README.md) |
| Write an adapter, or contribute | [Contributor guide](contributing/README.md) |

## For Integrators

Read in roughly this order:

1. [Quickstart](guides/quickstart.md): Python installation to first result.
2. [Python SDK guide](guides/python-sdk.md) and [Python reference](reference/api/README.md): the
   supported published SDK.
3. [C# SDK guide](guides/csharp-sdk.md), [C# reference](reference/csharp-sdk.md), and
   [migration map](guides/python-to-csharp.md): the independent native .NET 8 prerelease.
4. [Integrate AnyInfer](guides/README.md): choose the Python SDK, native C# SDK,
   command-line tool, or Python sidecar.
5. [Installation and extras](guides/installation.md): Python packages and extras.
6. [Shared configuration](reference/configuration.md): one file for the Python SDK, CLI,
   and sidecar. C# reads a restricted version 1 subset, documented on its
   [`AnyInferConfig` API page](https://anyinfer.dev/csharp/api/anyinfer.config.anyinferconfig/).
7. [Concepts](concepts/README.md): one line each; read them once and
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
