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

::: anyinfer.context.Strategy

::: anyinfer.context.RenderOrder

::: anyinfer.context.RankCache

</div>

## Selection

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.select

::: anyinfer.context.normalize_strategy

::: anyinfer.context.VALID_STRATEGIES

::: anyinfer.context.DEFAULT_MAX_DOCUMENTS

::: anyinfer.context.DEFAULT_MAX_BYTES

</div>

## Ranking

Public so it can be replaced: the shipped ranker is lexical, and an application needing
semantic retrieval ranks its own documents and passes the result through.

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.rank

::: anyinfer.context.build_rank_cache

::: anyinfer.context.tokenize

</div>

## Structure and tiers

<div class="anyinfer-api-block" markdown>

::: anyinfer.context.detect_language

::: anyinfer.context.structural_extract

::: anyinfer.context.is_generated_path

::: anyinfer.context.module_surfaces

::: anyinfer.context.DEFAULT_ROLLUP_SHARE

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

</div>
