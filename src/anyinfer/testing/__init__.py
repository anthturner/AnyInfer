"""Testing utilities: fake providers, cassettes, and the shared conformance suite.

Public on purpose — a third-party adapter certifies itself by running the same suite the
built-in adapters run.
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

__all__ = [
    "CONFORMANCE_CASES",
    "Capabilities",
    "CaseResult",
    "Cassette",
    "CassetteTransport",
    "ConformanceCase",
    "ConformanceHarness",
    "FakeGeminiServer",
    "FakeOllamaServer",
    "FakeOpenAIServer",
    "FakeResponse",
    "Interaction",
    "chunk_text",
    "matrix_row",
    "ndjson_lines",
    "results_to_json",
    "run_conformance",
    "sse_lines",
]
