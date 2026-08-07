"""Context reduction: fit a document corpus to a token budget.

**The boundary is strict.** Your application *collects* — walks the filesystem, applies
ignore rules, excludes secrets, asks the user what to share. This subpackage *reduces* —
ranks, selects, represents. It never opens a file, never touches the network, and adds no
dependencies, because collection is where the security policy lives and reduction is where
every application was writing the same code.

```python
from anyinfer import context

budget = client.budget(messages, target="anthropic:claude-sonnet-4-5")
reduction = context.select(
    [context.ContextDocument.of(path, text) for path, text in collected],
    query="how does credential resolution work?",
    max_tokens=budget.remaining_tokens or 8_000,
)
messages.insert(0, ai.user(reduction.text))
print(reduction.summary())
```

Five strategies, cheapest first:

- **`whole`** — send everything, when everything fits.
- **`ranked`** — the most relevant whole documents, in greedy rank order.
- **`tiered`** — *every* document represented, at decreasing fidelity: a module rollup,
  then structural extracts, then verbatim files.
- **`packed`** — chunk-level rank-and-pack, when the answer is one function in a big file.
- **`distill`** — map/reduce through your own client. The only strategy that spends
  inference, so it is a separate function rather than a `select()` strategy.

`auto` (the default) sends everything when it fits and falls back to `tiered`.

Reduction emulates a larger context window, and emulation announces itself: every result
carries what was kept, what was dropped, and which ceiling bound it, plus a content-free
`Reduction.summary()` and an optional `ContextReduced` telemetry event.
"""

from __future__ import annotations

from .distill import Distillation, SupportsGenerate, distill, distill_sync
from .documents import ContextDocument, RankCache
from .envelope import (
    render_chunk_block,
    render_corpus,
    render_extract_block,
    render_file_block,
)
from .pack import DEFAULT_CHUNK_TOKENS, Chunk, split_document
from .rank import build_rank_cache, rank, tokenize
from .select import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_DOCUMENTS,
    VALID_STRATEGIES,
    Reduction,
    RenderOrder,
    Strategy,
    normalize_strategy,
    select,
)
from .structure import detect_language, is_generated_path, structural_extract
from .tiers import DEFAULT_ROLLUP_SHARE, module_surfaces

__all__ = [
    "DEFAULT_CHUNK_TOKENS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DOCUMENTS",
    "DEFAULT_ROLLUP_SHARE",
    "VALID_STRATEGIES",
    "Chunk",
    "ContextDocument",
    "Distillation",
    "RankCache",
    "Reduction",
    "RenderOrder",
    "Strategy",
    "SupportsGenerate",
    "build_rank_cache",
    "detect_language",
    "distill",
    "distill_sync",
    "is_generated_path",
    "module_surfaces",
    "normalize_strategy",
    "rank",
    "render_chunk_block",
    "render_corpus",
    "render_extract_block",
    "render_file_block",
    "select",
    "split_document",
    "structural_extract",
    "tokenize",
]
