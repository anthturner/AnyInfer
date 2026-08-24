# Testing utilities

The `anyinfer.testing` package is public on purpose, for two audiences. An **application**
tests its own routing, repair, and reduction logic against a scripted provider — guide:
[test your application offline](../../guides/testing-your-app.md). A **third-party adapter**
certifies itself by running the same conformance suite the built-in adapters run — guide:
[the conformance suite](../../contributing/conformance.md).

## Scripted providers

A provider whose behaviour is declared per model, including the failures that are otherwise
unreachable without a real outage.

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.assert_manifest_matches

::: anyinfer.testing.ScriptedProvider

::: anyinfer.testing.ScriptedModel

::: anyinfer.testing.ScriptedFailure

::: anyinfer.testing.FailureKind

::: anyinfer.testing.DEFAULT_SCRIPTED_CAPABILITIES

::: anyinfer.testing.VOLATILE_FIELDS

::: anyinfer.testing.normalize

</div>

## Fake embedding and rerank providers

An in-process fake implementing `EmbedsText`/`ReranksText` directly — there is no wire
dialect to reproduce for these operations, so this fake needs no mock transport.

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.FakeEmbeddingRerankProvider

::: anyinfer.testing.ScriptedEmbeddingFailure

</div>

## Fake MCP server

An in-process Model Context Protocol server, for testing a tool loop fed by
[MCP tool sources](../../guides/tool-loop.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.FakeMCPServer

::: anyinfer.testing.FakeMCPTool

</div>

## pytest fixtures

Registered automatically when `anyinfer` is installed; see the guide for the full table.

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.plugin.EventCollector

</div>

## Fake providers

In-process fake servers that speak the real wire dialects, so examples and tests run
without credentials or a network.

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.FakeOpenAIServer

::: anyinfer.testing.FakeOllamaServer

::: anyinfer.testing.FakeGeminiServer

::: anyinfer.testing.FakeRetrievalServer

::: anyinfer.testing.FakeResponse

::: anyinfer.testing.scenario_responses

::: anyinfer.testing.CONFORMANCE_SCENARIOS

::: anyinfer.testing.chunk_text

::: anyinfer.testing.sse_lines

::: anyinfer.testing.ndjson_lines

</div>

## Cassettes

Record/replay of real provider exchanges.

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.Cassette

::: anyinfer.testing.CassetteTransport

::: anyinfer.testing.Interaction

</div>

## Conformance

The parametrized suite behind the [conformance matrix](../conformance-matrix.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.testing.conformance.run_conformance

::: anyinfer.testing.conformance.ConformanceHarness

::: anyinfer.testing.conformance.Capabilities

::: anyinfer.testing.conformance.ConformanceCase

::: anyinfer.testing.conformance.CaseResult

::: anyinfer.testing.conformance.CONFORMANCE_CASES

::: anyinfer.testing.conformance.PROBE_SCHEMA

::: anyinfer.testing.conformance.PROBE_TOOL

::: anyinfer.testing.conformance.matrix_row

::: anyinfer.testing.conformance.results_to_json

</div>
