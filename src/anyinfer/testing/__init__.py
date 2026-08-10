"""Testing utilities: scripted providers, fakes, cassettes, and the conformance suite.

Public on purpose, and for two audiences. A third-party adapter certifies itself by running
the same suite the built-in adapters run; an *application* tests its own routing, repair,
and reduction logic against `ScriptedProvider`, offline and deterministically. The pytest
fixtures in `anyinfer.testing.plugin` are registered automatically when ``anyinfer`` is
installed.

Both audiences share one stability promise: everything exported here is public API.
"""

from .cassettes import Cassette, CassetteTransport, Interaction
from .conformance import (
    CONFORMANCE_CASES,
    Capabilities,
    CaseResult,
    ConformanceCase,
    ConformanceHarness,
    matrix_row,
    results_to_json,
    run_conformance,
)
from .fakes import (
    FakeGeminiServer,
    FakeOllamaServer,
    FakeOpenAIServer,
    FakeResponse,
    chunk_text,
    ndjson_lines,
    sse_lines,
)
from .manifests import VOLATILE_FIELDS, assert_manifest_matches, normalize
from .mcp_fake import FakeMCPServer, FakeMCPTool
from .scripted import (
    DEFAULT_SCRIPTED_CAPABILITIES,
    FailureKind,
    ScriptedFailure,
    ScriptedModel,
    ScriptedProvider,
)

__all__ = [
    "CONFORMANCE_CASES",
    "DEFAULT_SCRIPTED_CAPABILITIES",
    "VOLATILE_FIELDS",
    "Capabilities",
    "CaseResult",
    "Cassette",
    "CassetteTransport",
    "ConformanceCase",
    "ConformanceHarness",
    "FailureKind",
    "FakeGeminiServer",
    "FakeMCPServer",
    "FakeMCPTool",
    "FakeOllamaServer",
    "FakeOpenAIServer",
    "FakeResponse",
    "Interaction",
    "ScriptedFailure",
    "ScriptedModel",
    "ScriptedProvider",
    "assert_manifest_matches",
    "chunk_text",
    "matrix_row",
    "ndjson_lines",
    "normalize",
    "results_to_json",
    "run_conformance",
    "sse_lines",
]
