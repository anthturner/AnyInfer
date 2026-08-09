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
  then structural extracts, then compact or verbatim files.
- **`packed`** — chunk-level rank-and-pack, when the answer is one function in a big file.
- **`distill`** — map/reduce through your own client. The only strategy that spends
  inference, so it is a separate function rather than a `select()` strategy.

`auto` (the default) sends everything when it fits and falls back to `tiered`.
`plan()` costs every strategy at once so the choice can be made from measurements.

Conversations are reduced too: `compact_history` shrinks a transcript that has outgrown
its window without breaking tool-call pairing, which is where naive truncation fails.

Everything algorithmic is a `ContextTuning` setting — duplicate collapse, selection order,
diversity, query expansion, corpus centrality, compact fallback. The defaults reproduce
the plain behaviour exactly, and `ContextTuning.recommended()` turns on the set worth
having for a source-code corpus.

Reduction emulates a larger context window, and emulation announces itself: every result
carries what was kept, what was dropped, what was collapsed, and which ceiling bound it,
plus a content-free `Reduction.summary()` and an optional `ContextReduced` telemetry event.
"""

from __future__ import annotations

from .compact import CompactSource, compact_source, supports_compaction
from .dedup import DuplicateMap, find_duplicates
from .distill import Distillation, SupportsGenerate, distill, distill_sync
from .documents import ContextDocument, RankCache
from .envelope import (
    ENVELOPE_FORMAT,
    render_chunk_block,
    render_compact_block,
    render_corpus,
    render_duplicate_block,
    render_extract_block,
    render_file_block,
)
from .history import (
    DEFAULT_KEEP_RECENT,
    HistoryCompaction,
    compact_history,
)
from .pack import DEFAULT_CHUNK_TOKENS, Chunk, split_document
from .rank import build_rank_cache, expand_query, rank, salience, tokenize
from .select import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_DOCUMENTS,
    VALID_STRATEGIES,
    Reduction,
    ReductionPlan,
    ReductionState,
    RenderOrder,
    Strategy,
    StrategyOutlook,
    normalize_strategy,
    plan,
    select,
)
from .settings import SELECTION_ORDERS, ContextTuning, SelectionOrder
from .structure import detect_language, imported_names, is_generated_path, structural_extract
from .tiers import DEFAULT_ROLLUP_SHARE, module_surfaces

__all__ = [
    "DEFAULT_CHUNK_TOKENS",
    "DEFAULT_KEEP_RECENT",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DOCUMENTS",
    "DEFAULT_ROLLUP_SHARE",
    "ENVELOPE_FORMAT",
    "SELECTION_ORDERS",
    "VALID_STRATEGIES",
    "Chunk",
    "CompactSource",
    "ContextDocument",
    "ContextTuning",
    "Distillation",
    "DuplicateMap",
    "HistoryCompaction",
    "RankCache",
    "Reduction",
    "ReductionPlan",
    "ReductionState",
    "RenderOrder",
    "SelectionOrder",
    "Strategy",
    "StrategyOutlook",
    "SupportsGenerate",
    "build_rank_cache",
    "compact_history",
    "compact_source",
    "detect_language",
    "distill",
    "distill_sync",
    "expand_query",
    "find_duplicates",
    "imported_names",
    "is_generated_path",
    "module_surfaces",
    "normalize_strategy",
    "plan",
    "rank",
    "render_chunk_block",
    "render_compact_block",
    "render_corpus",
    "render_duplicate_block",
    "render_extract_block",
    "render_file_block",
    "salience",
    "select",
    "split_document",
    "structural_extract",
    "supports_compaction",
    "tokenize",
]
