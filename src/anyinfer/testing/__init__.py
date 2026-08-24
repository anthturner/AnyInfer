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
    CONFORMANCE_SCENARIOS,
    FakeGeminiServer,
    FakeOllamaServer,
    FakeOpenAIServer,
    FakeResponse,
    FakeRetrievalServer,
    chunk_text,
    ndjson_lines,
    scenario_responses,
    sse_lines,
)
from .manifests import VOLATILE_FIELDS, assert_manifest_matches, normalize
from .mcp_fake import FakeMCPServer, FakeMCPTool
from .recording import SECRET_SHAPES, AuditFinding, audit_cassette, audit_interaction
from .scripted import (
    DEFAULT_SCRIPTED_CAPABILITIES,
    FailureKind,
    ScriptedFailure,
    ScriptedModel,
    ScriptedProvider,
)
from .scripted_operations import FakeEmbeddingRerankProvider, ScriptedEmbeddingFailure

__all__ = [
    "CONFORMANCE_CASES",
    "CONFORMANCE_SCENARIOS",
    "DEFAULT_SCRIPTED_CAPABILITIES",
    "SECRET_SHAPES",
    "VOLATILE_FIELDS",
    "AuditFinding",
    "Capabilities",
    "CaseResult",
    "Cassette",
    "CassetteTransport",
    "ConformanceCase",
    "ConformanceHarness",
    "FailureKind",
    "FakeEmbeddingRerankProvider",
    "FakeGeminiServer",
    "FakeMCPServer",
    "FakeMCPTool",
    "FakeOllamaServer",
    "FakeOpenAIServer",
    "FakeResponse",
    "FakeRetrievalServer",
    "Interaction",
    "ScriptedEmbeddingFailure",
    "ScriptedFailure",
    "ScriptedModel",
    "ScriptedProvider",
    "assert_manifest_matches",
    "audit_cassette",
    "audit_interaction",
    "chunk_text",
    "matrix_row",
    "ndjson_lines",
    "normalize",
    "results_to_json",
    "run_conformance",
    "scenario_responses",
    "sse_lines",
]
