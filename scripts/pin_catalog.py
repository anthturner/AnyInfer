#!/usr/bin/env python3
"""Pin the bundled local-model catalog against upstream repositories.

This is the **only** way numbers enter ``src/anyinfer/catalog/models.json``. Hashes, sizes,
revisions, and ``last_verified`` dates are read from upstream at run time and written
verbatim; nothing here invents a value, and a candidate whose files cannot be resolved is
reported and skipped rather than shipped half-pinned.

Two upstreams are consulted, both over plain JSON:

- Hugging Face — ``/api/models/{repo}/revision/{rev}`` for the immutable commit sha, then
  ``/api/models/{repo}/tree/{sha}?recursive=1`` for per-file sizes and LFS sha256 digests.
- The Ollama registry — ``/v2/library/{name}/manifests/{tag}`` for the manifest digest,
  because registry tags are mutable and only a digest makes drift detectable.

Run from the repository root::

    python scripts/pin_catalog.py                # refresh every candidate
    python scripts/pin_catalog.py qwen3-8b       # refresh selected model ids
    python scripts/pin_catalog.py --dry-run      # report without writing

A development tool: unlike the library it may use ``httpx``/``httpx2`` freely.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import httpx2

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "anyinfer" / "catalog" / "models.json"

HF_API = "https://huggingface.co/api/models"
HF_RESOLVE = "https://huggingface.co"
OLLAMA_REGISTRY = "https://registry.ollama.ai/v2/library"

_TIMEOUT = httpx2.Timeout(60.0)

# ---- the quantization ladder -----------------------------------------------------------

QUALITY_RANK: dict[str, int] = {
    "F16": 90,
    "BF16": 90,
    "Q8_0": 80,
    "Q6_K": 60,
    "Q5_K_M": 50,
    "Q5_K_S": 48,
    "MXFP4": 45,
    "Q4_K_M": 40,
    "Q4_K_S": 38,
    "Q4_0": 30,
    "IQ4_XS": 28,
    "IQ3_M": 25,
    "IQ2_M": 15,
}
"""Ladder position for each quantization; higher is better quality."""

SHIPPED_QUANTS: tuple[str, ...] = ("Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "MXFP4")
"""Quantizations the bundled catalog offers. Below Q4_K_M is opt-in, not curated."""

_QUANT_PATTERN = re.compile(
    r"(?:^|[-_.])(" + "|".join(sorted(QUALITY_RANK, key=len, reverse=True)) + r")(?:$|[-_.])",
    re.IGNORECASE,
)
_SHARD_PATTERN = re.compile(r"^(?P<stem>.+)-(?P<index>\d{5})-of-(?P<count>\d{5})\.gguf$")

AUXILIARY_MARKERS: tuple[str, ...] = ("mmproj", "eagle3", "eagle", "draft", "vocab", "lora")
"""File-name markers for GGUFs that are *not* the model.

A repository often ships companions alongside the weights: vision projectors, and
speculative-decoding draft heads that are a fraction of the size. Matching one of those as
"the Q8_0 variant" produces an entry that claims a 120B model is 800 MB, which is exactly
the kind of quietly-wrong number that pinning exists to prevent.
"""

# ---- memory estimation --------------------------------------------------------------
#
# A superset of anyinfer.local.tuning's _KV_BYTES_PER_TOKEN_F16, not an import of it: this
# script deliberately carries no dependency on the anyinfer package (see the module
# docstring), and the catalog needs finer parameter-size buckets than the runtime tuner's
# intentionally coarse context-ladder table. Every key this table shares with tuning.py's
# must carry the same bytes-per-token value — if you change one for a shared key, change
# the other too, or a catalog fit verdict and the runtime planner's own estimate will
# silently disagree for the same model.

KV_BYTES_PER_TOKEN_F16: dict[str, int] = {
    "1B": 64 * 1024,
    "1.5B": 96 * 1024,
    "1.7B": 96 * 1024,
    "1.9B": 96 * 1024,
    "3B": 128 * 1024,
    "3.8B": 128 * 1024,
    "4B": 128 * 1024,
    "7B": 256 * 1024,
    "8B": 256 * 1024,
    "9B": 256 * 1024,
    "12B": 400 * 1024,
    "13B": 400 * 1024,
    "14B": 400 * 1024,
    "20B": 512 * 1024,
    "24B": 512 * 1024,
    "27B": 576 * 1024,
    "30B": 640 * 1024,
    "32B": 640 * 1024,
    "70B": 1280 * 1024,
    "120B": 1280 * 1024,
}
_DEFAULT_KV = 256 * 1024
_ESTIMATE_CONTEXT = 8192
_CPU_OVERHEAD = 512 * 1024 * 1024
_GPU_OVERHEAD = 384 * 1024 * 1024

# ---- candidates -------------------------------------------------------------------------
#
# Repo choices follow the plan's source policy: the model author's official GGUF repo, then
# ggml-org, then bartowski/lmstudio-community. Licenses must be in the download allowlist.

CANDIDATES: tuple[Mapping[str, Any], ...] = (
    # --- general chat -------------------------------------------------------------------
    {
        "id": "llama-3.2-1b-instruct",
        "family": "llama-3.2",
        "display_name": "Llama 3.2 1B Instruct",
        "parameter_size": "1B",
        "context_window": 131072,
        "license": "llama-3.2-community",
        "best_at": ["low-resource", "drafting"],
        "repo": "bartowski/Llama-3.2-1B-Instruct-GGUF",
        "source": "https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct",
        "ollama": "llama3.2:1b",
    },
    {
        "id": "llama-3.2-3b-instruct",
        "family": "llama-3.2",
        "display_name": "Llama 3.2 3B Instruct",
        "parameter_size": "3B",
        "context_window": 131072,
        "license": "llama-3.2-community",
        "best_at": ["general-chat", "low-resource"],
        "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "source": "https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct",
        "ollama": "llama3.2:3b",
    },
    {
        "id": "llama-3.1-8b-instruct",
        "family": "llama-3.1",
        "display_name": "Llama 3.1 8B Instruct",
        "parameter_size": "8B",
        "context_window": 131072,
        "license": "llama-3.1-community",
        "best_at": ["general-chat", "tool-use"],
        "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "source": "https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct",
        "ollama": "llama3.1:8b",
    },
    {
        "id": "qwen2.5-1.5b-instruct",
        "family": "qwen2.5",
        "display_name": "Qwen2.5 1.5B Instruct",
        "parameter_size": "1.5B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["low-resource", "drafting"],
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "ollama": "qwen2.5:1.5b",
        "artifact_ids": {"Q4_K_M": "qwen2.5-1.5b-instruct-q4-k-m"},
    },
    {
        "id": "qwen2.5-7b-instruct",
        "family": "qwen2.5",
        "display_name": "Qwen2.5 7B Instruct",
        "parameter_size": "7B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "multilingual", "tool-use"],
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF",
        "ollama": "qwen2.5:7b",
        "artifact_ids": {"Q4_K_M": "qwen2.5-7b-instruct-q4-k-m"},
    },
    {
        "id": "qwen2.5-14b-instruct",
        "family": "qwen2.5",
        "display_name": "Qwen2.5 14B Instruct",
        "parameter_size": "14B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "multilingual"],
        "repo": "Qwen/Qwen2.5-14B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF",
        "ollama": "qwen2.5:14b",
    },
    {
        "id": "qwen2.5-32b-instruct",
        "family": "qwen2.5",
        "display_name": "Qwen2.5 32B Instruct",
        "parameter_size": "32B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "tool-use"],
        "repo": "Qwen/Qwen2.5-32B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF",
        "ollama": "qwen2.5:32b",
    },
    {
        "id": "qwen3-4b",
        "family": "qwen3",
        "display_name": "Qwen3 4B",
        "parameter_size": "4B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "reasoning", "low-resource"],
        "repo": "Qwen/Qwen3-4B-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen3-4B-GGUF",
        "ollama": "qwen3:4b",
    },
    {
        "id": "qwen3-8b",
        "family": "qwen3",
        "display_name": "Qwen3 8B",
        "parameter_size": "8B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "reasoning", "tool-use"],
        "repo": "Qwen/Qwen3-8B-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen3-8B-GGUF",
        "ollama": "qwen3:8b",
    },
    {
        "id": "qwen3-14b",
        "family": "qwen3",
        "display_name": "Qwen3 14B",
        "parameter_size": "14B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "reasoning"],
        "repo": "Qwen/Qwen3-14B-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen3-14B-GGUF",
        "ollama": "qwen3:14b",
    },
    {
        "id": "qwen3-32b",
        "family": "qwen3",
        "display_name": "Qwen3 32B",
        "parameter_size": "32B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["reasoning", "general-chat"],
        "repo": "Qwen/Qwen3-32B-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen3-32B-GGUF",
        "ollama": "qwen3:32b",
    },
    {
        "id": "qwen3-30b-a3b",
        "family": "qwen3",
        "display_name": "Qwen3 30B-A3B (MoE)",
        "parameter_size": "30B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat", "reasoning"],
        "repo": "Qwen/Qwen3-30B-A3B-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF",
        "ollama": "qwen3:30b",
    },
    {
        "id": "gemma-3-1b-it",
        "family": "gemma-3",
        "display_name": "Gemma 3 1B Instruct",
        "parameter_size": "1B",
        "context_window": 32768,
        "license": "gemma-terms",
        "best_at": ["low-resource"],
        "repo": "bartowski/google_gemma-3-1b-it-GGUF",
        "source": "https://huggingface.co/google/gemma-3-1b-it",
        "ollama": "gemma3:1b",
    },
    {
        "id": "gemma-3-4b-it",
        "family": "gemma-3",
        "display_name": "Gemma 3 4B Instruct",
        "parameter_size": "4B",
        "context_window": 131072,
        "license": "gemma-terms",
        "best_at": ["general-chat", "multilingual"],
        "repo": "bartowski/google_gemma-3-4b-it-GGUF",
        "source": "https://huggingface.co/google/gemma-3-4b-it",
        "ollama": "gemma3:4b",
    },
    {
        "id": "gemma-3-12b-it",
        "family": "gemma-3",
        "display_name": "Gemma 3 12B Instruct",
        "parameter_size": "12B",
        "context_window": 131072,
        "license": "gemma-terms",
        "best_at": ["general-chat", "long-context"],
        "repo": "bartowski/google_gemma-3-12b-it-GGUF",
        "source": "https://huggingface.co/google/gemma-3-12b-it",
        "ollama": "gemma3:12b",
    },
    {
        "id": "gemma-3-27b-it",
        "family": "gemma-3",
        "display_name": "Gemma 3 27B Instruct",
        "parameter_size": "27B",
        "context_window": 131072,
        "license": "gemma-terms",
        "best_at": ["general-chat", "multilingual"],
        "repo": "bartowski/google_gemma-3-27b-it-GGUF",
        "source": "https://huggingface.co/google/gemma-3-27b-it",
        "ollama": "gemma3:27b",
    },
    {
        "id": "phi-4",
        "family": "phi-4",
        "display_name": "Phi-4",
        "parameter_size": "14B",
        "context_window": 16384,
        "license": "mit",
        "best_at": ["reasoning", "math"],
        "repo": "microsoft/phi-4-gguf",
        "source": "https://huggingface.co/microsoft/phi-4",
        "ollama": "phi4",
    },
    {
        "id": "phi-4-mini-instruct",
        "family": "phi-4",
        "display_name": "Phi-4 Mini Instruct",
        "parameter_size": "3.8B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["low-resource", "reasoning"],
        "repo": "bartowski/microsoft_Phi-4-mini-instruct-GGUF",
        "source": "https://huggingface.co/microsoft/Phi-4-mini-instruct",
        "ollama": "phi4-mini",
    },
    {
        "id": "mistral-7b-instruct-v0.3",
        "family": "mistral",
        "display_name": "Mistral 7B Instruct v0.3",
        "parameter_size": "7B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["general-chat"],
        "repo": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        "source": "https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3",
        "ollama": "mistral:7b",
    },
    {
        "id": "mistral-nemo-instruct",
        "family": "mistral",
        "display_name": "Mistral Nemo Instruct",
        "parameter_size": "12B",
        "context_window": 131072,
        "license": "apache-2.0",
        "best_at": ["general-chat", "long-context", "multilingual"],
        "repo": "bartowski/Mistral-Nemo-Instruct-2407-GGUF",
        "source": "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407",
        "ollama": "mistral-nemo",
    },
    {
        "id": "mistral-small-3.2",
        "family": "mistral",
        "display_name": "Mistral Small 3.2 Instruct",
        "parameter_size": "24B",
        "context_window": 131072,
        "license": "apache-2.0",
        "best_at": ["general-chat", "tool-use"],
        "repo": "bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF",
        "source": "https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        "ollama": "mistral-small3.2",
    },
    {
        "id": "gpt-oss-20b",
        "family": "gpt-oss",
        "display_name": "gpt-oss 20B (MoE)",
        "parameter_size": "20B",
        "context_window": 131072,
        "license": "apache-2.0",
        "best_at": ["reasoning", "tool-use", "agentic"],
        "repo": "ggml-org/gpt-oss-20b-GGUF",
        "source": "https://huggingface.co/openai/gpt-oss-20b",
        "ollama": "gpt-oss:20b",
    },
    {
        "id": "gpt-oss-120b",
        "family": "gpt-oss",
        "display_name": "gpt-oss 120B (MoE)",
        "parameter_size": "120B",
        "context_window": 131072,
        "license": "apache-2.0",
        "best_at": ["reasoning", "agentic"],
        "repo": "ggml-org/gpt-oss-120b-GGUF",
        "source": "https://huggingface.co/openai/gpt-oss-120b",
        "ollama": "gpt-oss:120b",
    },
    {
        "id": "granite-3.3-8b-instruct",
        "family": "granite",
        "display_name": "Granite 3.3 8B Instruct",
        "parameter_size": "8B",
        "context_window": 131072,
        "license": "apache-2.0",
        "best_at": ["rag", "tool-use"],
        "repo": "ibm-granite/granite-3.3-8b-instruct-GGUF",
        "source": "https://huggingface.co/ibm-granite/granite-3.3-8b-instruct",
        "ollama": "granite3.3:8b",
    },
    {
        "id": "smollm2-1.7b-instruct",
        "family": "smollm2",
        "display_name": "SmolLM2 1.7B Instruct",
        "parameter_size": "1.7B",
        "context_window": 8192,
        "license": "apache-2.0",
        "best_at": ["low-resource", "drafting"],
        "repo": "HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF",
        "source": "https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct",
        "ollama": "smollm2:1.7b",
    },
    {
        "id": "olmo-2-7b-instruct",
        "family": "olmo-2",
        "display_name": "OLMo 2 7B Instruct",
        "parameter_size": "7B",
        "context_window": 4096,
        "license": "apache-2.0",
        "best_at": ["general-chat"],
        "repo": "allenai/OLMo-2-1124-7B-Instruct-GGUF",
        "source": "https://huggingface.co/allenai/OLMo-2-1124-7B-Instruct",
        "ollama": "olmo2:7b",
    },
    {
        "id": "falcon3-7b-instruct",
        "family": "falcon3",
        "display_name": "Falcon 3 7B Instruct",
        "parameter_size": "7B",
        "context_window": 32768,
        "license": "falcon-llm-2.0",
        "best_at": ["general-chat", "math"],
        "repo": "tiiuae/Falcon3-7B-Instruct-GGUF",
        "source": "https://huggingface.co/tiiuae/Falcon3-7B-Instruct",
        "ollama": "falcon3:7b",
    },
    {
        "id": "hermes-3-llama-3.1-8b",
        "family": "hermes-3",
        "display_name": "Hermes 3 (Llama 3.1 8B)",
        "parameter_size": "8B",
        "context_window": 131072,
        "license": "llama-3.1-community",
        "best_at": ["tool-use", "agentic", "general-chat"],
        "repo": "NousResearch/Hermes-3-Llama-3.1-8B-GGUF",
        "source": "https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B",
        "ollama": "hermes3:8b",
    },
    {
        "id": "glm-4-9b-chat",
        "family": "glm-4",
        "display_name": "GLM-4 9B Chat",
        "parameter_size": "9B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["general-chat", "multilingual"],
        "repo": "bartowski/THUDM_GLM-4-9B-0414-GGUF",
        "source": "https://huggingface.co/THUDM/GLM-4-9B-0414",
        "ollama": "glm4:9b",
    },
    # --- reasoning ----------------------------------------------------------------------
    {
        "id": "deepseek-r1-distill-qwen-1.5b",
        "family": "deepseek-r1",
        "display_name": "DeepSeek-R1 Distill Qwen 1.5B",
        "parameter_size": "1.5B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["reasoning", "low-resource"],
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
        "ollama": "deepseek-r1:1.5b",
    },
    {
        "id": "deepseek-r1-distill-qwen-7b",
        "family": "deepseek-r1",
        "display_name": "DeepSeek-R1 Distill Qwen 7B",
        "parameter_size": "7B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["reasoning", "math"],
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "ollama": "deepseek-r1:7b",
    },
    {
        "id": "deepseek-r1-distill-qwen-14b",
        "family": "deepseek-r1",
        "display_name": "DeepSeek-R1 Distill Qwen 14B",
        "parameter_size": "14B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["reasoning", "math"],
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        "ollama": "deepseek-r1:14b",
    },
    {
        "id": "deepseek-r1-distill-qwen-32b",
        "family": "deepseek-r1",
        "display_name": "DeepSeek-R1 Distill Qwen 32B",
        "parameter_size": "32B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["reasoning", "math"],
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "ollama": "deepseek-r1:32b",
    },
    {
        "id": "deepseek-r1-distill-llama-70b",
        "family": "deepseek-r1",
        "display_name": "DeepSeek-R1 Distill Llama 70B",
        "parameter_size": "70B",
        "context_window": 131072,
        "license": "mit",
        "best_at": ["reasoning"],
        "repo": "bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF",
        "source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        "ollama": "deepseek-r1:70b",
    },
    {
        "id": "qwq-32b",
        "family": "qwq",
        "display_name": "QwQ 32B",
        "parameter_size": "32B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["reasoning", "math"],
        "repo": "Qwen/QwQ-32B-GGUF",
        "source": "https://huggingface.co/Qwen/QwQ-32B",
        "ollama": "qwq",
    },
    # --- coding -------------------------------------------------------------------------
    {
        "id": "qwen2.5-coder-1.5b-instruct",
        "family": "qwen2.5-coder",
        "display_name": "Qwen2.5-Coder 1.5B Instruct",
        "parameter_size": "1.5B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["code-completion", "low-resource"],
        "repo": "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        "ollama": "qwen2.5-coder:1.5b",
    },
    {
        "id": "qwen2.5-coder-7b-instruct",
        "family": "qwen2.5-coder",
        "display_name": "Qwen2.5-Coder 7B Instruct",
        "parameter_size": "7B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["coding", "code-completion"],
        "repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "ollama": "qwen2.5-coder:7b",
    },
    {
        "id": "qwen2.5-coder-14b-instruct",
        "family": "qwen2.5-coder",
        "display_name": "Qwen2.5-Coder 14B Instruct",
        "parameter_size": "14B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["coding"],
        "repo": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
        "ollama": "qwen2.5-coder:14b",
    },
    {
        "id": "qwen2.5-coder-32b-instruct",
        "family": "qwen2.5-coder",
        "display_name": "Qwen2.5-Coder 32B Instruct",
        "parameter_size": "32B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["coding", "agentic"],
        "repo": "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF",
        "source": "https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF",
        "ollama": "qwen2.5-coder:32b",
    },
    {
        "id": "devstral-small",
        "family": "devstral",
        "display_name": "Devstral Small",
        "parameter_size": "24B",
        "context_window": 131072,
        "license": "apache-2.0",
        "best_at": ["agentic", "coding"],
        "repo": "bartowski/mistralai_Devstral-Small-2507-GGUF",
        "source": "https://huggingface.co/mistralai/Devstral-Small-2507",
        "ollama": "devstral",
    },
    {
        "id": "starcoder2-7b",
        "family": "starcoder2",
        "display_name": "StarCoder2 7B",
        "parameter_size": "7B",
        "context_window": 16384,
        "license": "openrail-m",
        "best_at": ["code-completion"],
        "repo": "second-state/StarCoder2-7B-GGUF",
        "source": "https://huggingface.co/bigcode/starcoder2-7b",
        "ollama": "starcoder2:7b",
    },
    # --- vision (catalog data ahead of request-side image support) -----------------------
    {
        "id": "qwen2.5-vl-7b-instruct",
        "family": "qwen2.5-vl",
        "display_name": "Qwen2.5-VL 7B Instruct",
        "parameter_size": "7B",
        "context_window": 32768,
        "license": "apache-2.0",
        "best_at": ["vision", "general-chat"],
        "repo": "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
        "projector": "mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf",
        "source": "https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct",
        "ollama": "qwen2.5vl:7b",
    },
)


# ---- Hugging Face ------------------------------------------------------------------------


def resolve_revision(client: httpx2.Client, repo: str, revision: str = "main") -> str | None:
    """Resolve a branch or tag to its immutable commit sha."""
    response = client.get(f"{HF_API}/{repo}/revision/{revision}")
    if response.status_code != 200:
        return None
    sha = response.json().get("sha")
    return str(sha) if isinstance(sha, str) and len(sha) == 40 else None


def fetch_tree(client: httpx2.Client, repo: str, sha: str) -> list[Mapping[str, Any]]:
    """List every file at a commit, with sizes and LFS digests."""
    entries: list[Mapping[str, Any]] = []
    cursor: str | None = f"{HF_API}/{repo}/tree/{sha}?recursive=1"
    while cursor:
        response = client.get(cursor)
        if response.status_code != 200:
            return []
        payload = response.json()
        if not isinstance(payload, list):
            return []
        entries.extend(e for e in payload if isinstance(e, dict))
        link = response.headers.get("link", "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        cursor = match.group(1) if match else None
    return entries


def detect_quantization(path: str) -> str | None:
    """Extract the quantization token from a GGUF file name, if it has one."""
    match = _QUANT_PATTERN.search(Path(path).stem)
    return match.group(1).upper() if match else None


def group_gguf_variants(
    entries: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Group a repo's GGUF files into shard sets keyed by quantization."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for entry in entries:
        path = str(entry.get("path", ""))
        lowered = path.lower()
        if not lowered.endswith(".gguf"):
            continue
        if any(marker in lowered for marker in AUXILIARY_MARKERS):
            continue
        quant = detect_quantization(path)
        if quant is None:
            continue
        grouped.setdefault(quant, []).append(entry)

    for quant, files in grouped.items():
        files.sort(key=lambda e: str(e.get("path", "")))
        grouped[quant] = _shard_set(files)
    return grouped


def _shard_set(files: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Keep one complete shard set, discarding files from a different split of the same quant.

    A repo can hold both ``model-Q4_K_M.gguf`` and a sharded ``model-Q4_K_M-00001-of-00002``
    split of a *different* model size. Prefer whichever set the first file belongs to.
    """
    first = str(files[0].get("path", ""))
    match = _SHARD_PATTERN.match(Path(first).name)
    if match is None:
        return [files[0]]
    stem = match.group("stem")
    count = int(match.group("count"))
    members = [
        f
        for f in files
        if (m := _SHARD_PATTERN.match(Path(str(f.get("path", ""))).name)) is not None
        and m.group("stem") == stem
    ]
    return members if len(members) == count else []


def digest_of(entry: Mapping[str, Any]) -> str | None:
    """The sha256 of a file's content, which for LFS objects is the ``lfs.oid``."""
    lfs = entry.get("lfs")
    if isinstance(lfs, Mapping):
        oid = lfs.get("oid")
        if isinstance(oid, str) and len(oid) == 64:
            return oid
    return None


# ---- Ollama ------------------------------------------------------------------------------


def ollama_digest(client: httpx2.Client, tag: str) -> str | None:
    """Resolve an Ollama library tag to its manifest digest.

    Tags are mutable, so only a recorded digest makes a moved tag detectable.
    """
    name, _, version = tag.partition(":")
    response = client.get(
        f"{OLLAMA_REGISTRY}/{name}/manifests/{version or 'latest'}",
        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
    )
    if response.status_code != 200:
        return None
    header = response.headers.get("docker-content-digest")
    if header:
        return str(header)
    config = response.json().get("config")
    if isinstance(config, Mapping) and isinstance(config.get("digest"), str):
        return str(config["digest"])
    return None


# ---- estimation ---------------------------------------------------------------------------


def estimate_memory(parameter_size: str | None, file_bytes: int) -> tuple[int, int]:
    """Return ``(est_ram_bytes, est_vram_bytes)`` for a weight file of this size.

    Weights plus an 8k-context KV cache plus fixed runtime overhead — the same coarse
    arithmetic the tuner uses, stored as numbers so the fit engine stays trivial.
    """
    per_token = KV_BYTES_PER_TOKEN_F16.get((parameter_size or "").upper(), _DEFAULT_KV)
    kv = per_token * _ESTIMATE_CONTEXT
    return file_bytes + kv + _CPU_OVERHEAD, file_bytes + kv + _GPU_OVERHEAD


# ---- pinning ------------------------------------------------------------------------------


def pin_model(
    client: httpx2.Client, candidate: Mapping[str, Any], today: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve one candidate into a fully pinned catalog entry."""
    notes: list[str] = []
    repo = str(candidate["repo"])
    sha = resolve_revision(client, repo)
    if sha is None:
        return None, [f"{candidate['id']}: cannot resolve revision for {repo}"]

    tree = fetch_tree(client, repo, sha)
    if not tree:
        return None, [f"{candidate['id']}: empty or unreadable tree for {repo}@{sha[:12]}"]

    grouped = group_gguf_variants(tree)
    projector: Mapping[str, Any] | None = None
    projector_name = candidate.get("projector")
    if projector_name:
        projector = next(
            (entry for entry in tree if str(entry.get("path", "")) == str(projector_name)),
            None,
        )
        if projector is None or digest_of(projector) is None:
            return None, [
                f"{candidate['id']}: projector {projector_name!r} is absent or unverifiable"
            ]
    projector_digest = digest_of(projector) if projector is not None else None
    artifact_ids = dict(candidate.get("artifact_ids") or {})
    variants: list[dict[str, Any]] = []

    for quant in SHIPPED_QUANTS:
        files = grouped.get(quant)
        if not files:
            continue
        digests: dict[str, str] = {}
        sizes: dict[str, int] = {}
        unverifiable = False
        for entry in files:
            path = str(entry["path"])
            digest = digest_of(entry)
            if digest is None:
                unverifiable = True
                break
            digests[path] = digest
            sizes[path] = int(entry.get("size", 0))
        roles: dict[str, str] = {}
        if projector is not None and projector_digest is not None:
            path = str(projector["path"])
            digests[path] = projector_digest
            sizes[path] = int(projector.get("size", 0))
            roles[path] = "projector"
        if unverifiable or not digests:
            notes.append(f"{candidate['id']}: {quant} has no LFS digest; skipped")
            continue

        total = sum(sizes.values())
        est_ram, est_vram = estimate_memory(candidate.get("parameter_size"), total)
        variant_id = f"{candidate['id']}-{quant.lower().replace('_', '-')}"
        variants.append(
            {
                "id": variant_id,
                "engine": "llama.cpp",
                "kind": "gguf",
                "quantization": quant,
                "quality_rank": QUALITY_RANK[quant],
                "est_file_bytes": total,
                "est_ram_bytes": est_ram,
                "est_vram_bytes": est_vram,
                "artifact_id": artifact_ids.get(quant, variant_id),
                "source": {
                    "resolver": "huggingface",
                    "repo": repo,
                    "revision": sha,
                    "files": list(digests),
                    "sha256": {k: digests[k] for k in sorted(digests)},
                    "size_bytes": {k: sizes[k] for k in sorted(sizes)},
                    **({"roles": roles} if roles else {}),
                },
            }
        )

    if not variants:
        return None, [*notes, f"{candidate['id']}: no shippable quantization found in {repo}"]

    default = min(variants, key=lambda v: abs(int(v["quality_rank"]) - QUALITY_RANK["Q4_K_M"]))
    sources: dict[str, Any] = {}
    tag = candidate.get("ollama")
    if tag:
        digest = ollama_digest(client, str(tag))
        entry_ollama: dict[str, Any] = {"tag": str(tag)}
        if digest:
            entry_ollama["digest"] = digest
        else:
            notes.append(f"{candidate['id']}: Ollama tag {tag} has no resolvable digest")
        sources["ollama"] = entry_ollama

    return (
        {
            "id": candidate["id"],
            "family": candidate.get("family", ""),
            "display_name": candidate.get("display_name", ""),
            "parameter_size": candidate.get("parameter_size"),
            "quantization": str(default["quantization"]),
            "context_window": candidate.get("context_window"),
            "license": candidate.get("license", ""),
            "best_at": list(candidate.get("best_at", ())),
            "est_file_bytes": default["est_file_bytes"],
            "est_ram_bytes": default["est_ram_bytes"],
            "est_vram_bytes": default["est_vram_bytes"],
            "last_verified": today,
            "source": candidate.get("source", f"https://huggingface.co/{repo}"),
            "sources": sources,
            "variants": variants,
        },
        notes,
    )


_COMMENT = [
    "Bundled logical model catalog for local inference (llama.cpp + Ollama channels).",
    "Machine-maintained: every value here is written by scripts/pin_catalog.py from",
    "upstream Hugging Face and Ollama registry responses. Never hand-edit a hash, a size,",
    "a revision, or a last_verified date -- re-run the pin script instead.",
    "Validated by scripts/validate_catalog.py; drift-checked by scripts/check_catalog_drift.py.",
    "Deliberately excluded for licensing (reachable via an application overlay): Codestral",
    "22B (MNPL, non-production), Command R7B (CC-BY-NC), Qwen2.5 3B and 72B (Qwen research",
    "license), Ministral 8B (Mistral research license), DeepSeek-Coder-V2-Lite (bespoke",
    "model license).",
    "A vision candidate must name one exact projector; the pinning pass verifies and records",
    "that companion beside every weight variant rather than matching an mmproj heuristically.",
]


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh the bundled model catalog from upstream."""
    parser = argparse.ArgumentParser(description="Pin the bundled local model catalog.")
    parser.add_argument("models", nargs="*", help="model ids to refresh; default is all")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    wanted = set(args.models)
    candidates = [c for c in CANDIDATES if not wanted or c["id"] in wanted]
    if not candidates:
        print(f"no candidates matched {sorted(wanted)}", file=sys.stderr)
        return 2

    existing: dict[str, Any] = {}
    if args.output.exists():
        document = json.loads(args.output.read_text(encoding="utf-8"))
        existing = {entry["id"]: entry for entry in document.get("models", [])}

    today = date.today().isoformat()
    notes: list[str] = []
    with httpx2.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
        for candidate in candidates:
            entry, candidate_notes = pin_model(client, candidate, today)
            notes.extend(candidate_notes)
            if entry is None:
                print(f"  skip  {candidate['id']}")
                continue
            existing[str(candidate["id"])] = entry
            size = int(entry["est_file_bytes"]) / 1024**3
            print(f"  pin   {candidate['id']}  ({len(entry['variants'])} variants, {size:.1f} GB)")

    for note in notes:
        print(f"  note  {note}", file=sys.stderr)

    document = {
        "format_version": 1,
        "_comment": _COMMENT,
        "generated": today,
        "models": [existing[key] for key in sorted(existing)],
    }
    if args.dry_run:
        print(f"\ndry run: {len(document['models'])} models would be written")
        return 0

    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {len(document['models'])} models to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
