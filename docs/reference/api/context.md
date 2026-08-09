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
[`anyinfer context`](../../guides/cli.md).

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
