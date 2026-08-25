# Context reduction

Fit a document corpus to a token budget. Your application collects; this subpackage
reduces. The reasoning and the strategy tradeoffs are in
[context reduction](../../concepts/context-reduction.md); the task-oriented walkthrough is
[fitting a corpus to a budget](../../guides/fitting-context.md).

Imported from its own path, like the other optional subsystems:

```python
from anyinfer import context
```

## Documents and results

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.ContextDocument

::: anyinfer.context.Reduction

::: anyinfer.context.ReductionState

::: anyinfer.context.Strategy

::: anyinfer.context.RenderOrder

::: anyinfer.context.RankCache

</div>

## Advanced settings

One record carries every algorithmic choice. The same field names are the `context` block
of the [configuration file](../configuration.md) and the `--context-*` flags of
[`anyinfer context`](../../guides/cli.md). Every setting that changes what gets sent is
off by default; `ContextTuning.recommended()` enables the set worth having for a
source-code corpus.

| Setting | Default | What it changes |
|---|---|---|
| `collapse_duplicates` | `True` | Render byte-identical documents once |
| `near_duplicate_threshold` | `0.0` | Collapse merely *similar* documents too |
| `selection_order` | `"rank"` | `"density"` admits by score per token |
| `diversity` | `0.0` | Penalize candidates resembling what is already chosen |
| `split_identifiers` | `False` | Tokenize compound identifiers into their parts |
| `query_expansion` | `False` | Pseudo-relevance feedback before ranking |
| `salience_weight` | `0.0` | Blend in import-graph centrality |
| `compact_fallback` | `False` | Shorten a document rather than drop it |
| `carry_over_bonus` | `0.0` | Keep the previous turn's selection, with `previous=` |
| `chunk_tokens` | `512` | Chunk size for `packed` and `distill` |
| `rollup_share` | `0.45` | Budget share `tiered` reserves for its rollup |

Two orderings deserve a note. `"rank"` admits documents strongest-first; `"density"`
admits them by score divided by token cost, which packs measurably more relevance into a
fixed budget (the classic knapsack result) at the risk of preferring two good small files
over one great large one. `diversity` penalizes each candidate by how much it resembles
what is already selected — multiplicatively, `value * (1 - diversity * similarity)`,
because the two value scales differ by orders of magnitude — so a budget is not spent on
eight files that say the same thing.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.ContextTuning

::: anyinfer.context.SelectionOrder

::: anyinfer.context.SELECTION_ORDERS

</div>

## Selection

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.select

::: anyinfer.context.normalize_strategy

::: anyinfer.context.VALID_STRATEGIES

::: anyinfer.context.DEFAULT_MAX_DOCUMENTS

::: anyinfer.context.DEFAULT_MAX_BYTES

</div>

## Planning

Cost every strategy before committing to one. Spends no inference and performs no I/O.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.plan

::: anyinfer.context.ReductionPlan

::: anyinfer.context.StrategyOutlook

</div>

## Duplicate collapse

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.find_duplicates

::: anyinfer.context.DuplicateMap

</div>

## History compaction

Reduce a conversation rather than a corpus, without breaking tool-call pairing. Call it
yourself, or hand `anyinfer.HistoryPolicy` to a client and let every frontend built on that
client apply the same rules on the request path.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.compact_history

::: anyinfer.context.HistoryCompaction

::: anyinfer.context.DEFAULT_KEEP_RECENT

::: anyinfer.HistoryPolicy

</div>

## Ranking

Public so it can be replaced: the shipped ranker is lexical, and an application needing
semantic retrieval ranks its own documents and passes the result through.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.rank

::: anyinfer.context.SemanticRanker

::: anyinfer.semantic_ranker

::: anyinfer.context.build_rank_cache

::: anyinfer.context.tokenize

::: anyinfer.context.expand_query

::: anyinfer.context.salience

</div>

## Structure and tiers

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.detect_language

::: anyinfer.context.structural_extract

::: anyinfer.context.imported_names

::: anyinfer.context.is_generated_path

::: anyinfer.context.module_surfaces

::: anyinfer.context.DEFAULT_ROLLUP_SHARE

</div>

## Compaction

The fidelity between a structural extract and a whole file.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.compact_source

::: anyinfer.context.CompactSource

::: anyinfer.context.supports_compaction

</div>

## Chunking

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.Chunk

::: anyinfer.context.split_document

::: anyinfer.context.DEFAULT_CHUNK_TOKENS

</div>

## Distillation

The only reduction that spends inference. See
[distill a corpus](../../examples/distill-a-corpus.md) for the cookbook.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.distill

::: anyinfer.context.distill_sync

::: anyinfer.context.Distillation

::: anyinfer.context.SupportsGenerate

</div>

## Rendering

The envelope format, exposed for applications that parse reduced context back out of
stored transcripts.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.render_corpus

::: anyinfer.context.render_file_block

::: anyinfer.context.render_extract_block

::: anyinfer.context.render_chunk_block

::: anyinfer.context.render_compact_block

::: anyinfer.context.render_duplicate_block

::: anyinfer.context.ENVELOPE_FORMAT

</div>
