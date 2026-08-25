# The Model Catalog

The catalog answers three questions in sequence: what local models exist, whether this
machine can run them, and how a pick becomes verified bytes an engine can load. It serves
two shapes of caller over the same data:

- *"Just give me a good default"*: the tier ladder (`small`, `medium`, `large`).
- *"Let me see what I could run"*: the model catalog, forty-odd curated local models,
  each annotated with whether this machine can run it.

They are bridged, not merged: a user's pick from the catalog flows into the ladder, so an
application can offer both without maintaining two code paths.

## What Is in It

`models.json` ships with AnyInfer and holds one row per logical model:

```python
from anyinfer import load_default_catalog

catalog = load_default_catalog()
entry = catalog.model("qwen2.5-7b-instruct")

entry.display_name  # 'Qwen2.5 7B Instruct'
entry.parameter_size  # '7B'
entry.license  # 'apache-2.0'
entry.best_at  # ('general-chat', 'multilingual', 'tool-use')
entry.channels  # ('llama-cpp', 'ollama')
entry.est_file_bytes  # 4683073632
```

Each entry carries a quantization ladder (the same model at Q8_0, Q6_K, Q5_K_M, and
Q4_K_M), because "which model" and "at what quality" are different questions, and the
second depends on the hardware:

```python
for variant in entry.variants_for("llama.cpp"):
    print(variant.quantization, variant.est_file_bytes)
# Q8_0   8.10 GB
# Q6_K   6.25 GB
# Q5_K_M 5.44 GB
# Q4_K_M 4.68 GB
```

Most models are published through two channels, recorded per entry. A GGUF file set (a
repository, an immutable commit, named files, a SHA-256 per file) is what AnyInfer
downloads and verifies itself for the supervised [llama.cpp path](local.md). An Ollama
registry tag is what gets recommended when the Ollama daemon owns the store; its manifest
digest is recorded so a moved tag is detectable.

Every row also states its `kind`: `"generation"` (the default) or `"embedding"`. Both are
acquired identically, so they share one table. An embedding row carries `dimensions` and
`max_input_tokens`, budgets memory from its own architecture rather than a chat model's,
reports only the `embedding` operation so a chat request never routes to it, and is
excluded from the `small`/`medium`/`large` ladder; those tiers answer "how big a chat
model should I run", which an embedding model has no answer to.

```python
for entry in catalog.models_for(kind="embedding"):
    print(entry.id, entry.embedding.dimensions)
```

`best_at` is a closed vocabulary (`general-chat`, `coding`, `reasoning`, `vision`,
`long-context`, and nine others); a free-text tag set would drift into synonyms nobody
can filter on.

## Will It Run?

`local_catalog()` classifies every entry against this machine:

```python
view = client.local_catalog("llama-cpp", best_at="coding")

for entry in view.runnable:
    print(entry.model.id, entry.fit.level, entry.fit.reasons[0])
```

| Level | Meaning |
|---|---|
| `gpu` | Fits comfortably in the accelerator's memory budget. |
| `cpu` | Too large for the GPU, but fits in system RAM. Runs, more slowly. |
| `tight` | Fits, with little room left for a longer context. |
| `no` | Exceeds this machine's memory entirely. |
| `unknown` | The numbers needed to judge are not available. |

Entries come back best-fit-first, deterministically ordered, and every verdict carries
its reasons, so "why did it say tight?" is answerable from the returned object alone:

```python
entry.fit.reasons
# ('needs 8.4 GiB of VRAM against a 9.0 GiB budget — it fits, but with little room
#   for a longer context',
#  'planning for the vulkan runtime; installing the CUDA runtime would give better
#   throughput on this NVIDIA device')
```

### When the Model Runs Somewhere Else

Ollama can point at another machine, and probing *this* machine would then describe the
wrong computer. Since no Ollama API reports its host's specifications, the view says so
instead of guessing, and allows the caller to supply the numbers:

```python
view = await client.local_catalog("ollama")
view.hardware_source  # 'unavailable' — ask the user for the remote host's specs

specs = local.HardwareProfile.from_user_input(ram_gb=64, vram_gb=24, accelerator="cuda")
view = await client.local_catalog("ollama", hardware=specs)
view.hardware_source  # 'provided'
```

Anything omitted stays unknown rather than becoming zero. A remote engine may also sit
behind a metered proxy, so its per-token cost reports as unknown rather than the genuine
zero a loopback engine gets; see [cost](cost.md).

## Using a Pick as Your Default Tier

The bridge between the two shapes is one call:

```python
catalog = load_default_catalog().with_alias_target("medium", "llama-cpp", "qwen2.5-14b-instruct")
client = ai.Client(providers=[...], catalog=catalog)

client.generate(prompt, target="medium")  # now resolves to the user's pick
```

Overlays produce new catalogs rather than mutating shared ones. Applications can overlay
whole model entries the same way: the supported route for models the bundled catalog
excludes, such as anything under non-commercial or research-only terms.

## Acquiring a Pick

```python
report = client.acquire_model("qwen2.5-7b-instruct", progress=on_progress)
report.plan.quantization  # 'Q5_K_M' — chosen for this machine, not assumed
report.entry.handle  # the file llama-server will be launched against
```

The quantization is chosen, not assumed: the highest-quality rung whose weights *and KV
cache* fit the memory budget, preferring a rung resident on the GPU over a better one
that would page through the CPU. Below Q4, the policy prefers a smaller model at a good
quantization over a bigger model at a bad one, so when nothing at Q4_K_M or better fits,
acquisition refuses with the arithmetic rather than handing back a two-bit quantization.
Pass `local.VariantPrefs(allow_low_quality=True)` to override. For vLLM the ladder has
hard hardware gates (FP8 needs NVIDIA compute capability 8.9, Marlin GPTQ 8.0, AWQ 7.5);
an unreported capability excludes a gated variant, since guessing produces a download
that fails at model load.

### Know the Cost Before You Pay It

```python
report = await client.acquire_model("gpt-oss-120b", dry_run=True)

report.plan.total_bytes  # 63_387_346_208
report.plan.already_have_bytes  # what a previous interrupted run already fetched
report.plan.remaining_bytes  # what this run would actually transfer
```

Nothing is written; this is what an application needs to put a real confirmation dialog
in front of a sixty-gigabyte download. Before any transfer starts, free disk space is
checked against what remains plus ten percent.

Progress reports aggregate figures for the whole acquisition: the total is known before
the first byte (sizes are pinned in the catalog), bytes already on disk count toward the
fraction, and rate and ETA stay `None` until there is a real sample. Callbacks are
throttled and may arrive from a worker thread; a sink that raises is recorded once as a
warning and then dropped, because a broken progress bar must not fail a download.

Interrupting is not deleting: cancel and the partial transfers stay on disk, run again
and it resumes. Nothing is registered until every file verifies, so a half-complete
model is invisible rather than half-usable.

### What Gets Verified

| Where the file came from | What is checked |
|---|---|
| A pinned catalog artifact | The SHA-256 in the catalog. A mismatch is a hard failure. |
| A Hugging Face repository | The digest the API reports for that file, checked against the bytes. |
| A URL supplied with a digest | The supplied digest. A mismatch is a hard failure. |
| A URL supplied with no digest | Refused, unless `allow_unverified=True` is passed. |

API digests are trust-on-first-use: the API is trusted for what the bytes should be,
then the bytes are verified against it, which turns a later upstream change into a
detectable event. An unverified file is recorded as unverified all the way out to
`locate_model()`: "AnyInfer checked these bytes" and "AnyInfer found these bytes" are
different claims.

Two rules apply to every acquisition and are not optional. File names from a remote API
are treated as attacker-influenced input: absolute paths, `..` segments, drive letters,
NUL bytes, and reserved Windows device names are rejected, and every destination is
checked for containment after resolution so a symlink cannot escape. And pickle-format
weights (`*.bin`, `*.pt`, `*.pth`, `*.ckpt`) are never fetched by default, because they
execute arbitrary code on load; acquisition fails with a hint naming the risk.

### Finding It Again

```python
located = client.locate_model("qwen2.5-7b-instruct")

located.path  # a file for GGUF, a directory for a snapshot
located.verified  # whether every file was checked against a digest
located.launch_hints  # {'engine': 'llama.cpp', 'model': '…', 'ctx_size': 32768, …}
```

Lookups do no network I/O and no re-hashing (size and modification time are compared
against the index; pass `verify=True` to force the full check). `launch_hints` is
advisory data, not process control: the llama.cpp supervisor consumes the hints
automatically, while for vLLM they are what a developer would paste into a command line;
AnyInfer acquires and locates vLLM weights but does not start a vLLM process.

Models live under revision-scoped directories in the platform's data directory
(`ANYINFER_MODEL_DIR` or `Client(model_dir=...)` overrides it), indexed by a
`store.json` that is a cache, not the truth: a missing or corrupt index is tolerated
and `rebuild_index()` recovers by rescanning. Nothing is ever evicted automatically:
`disk_usage()` and `remove_model()` give an application what it needs to build its own
policy.

### Engines That Keep Their Own Store

Some engines already have a store, a registry, and a downloader. For those the useful
operation is not "download these bytes" but "make yourself ready":

```python
report = client.pull_model("ollama", "qwen3:8b")

report.already_present  # True when nothing had to move
report.bytes_transferred
```

Those bytes land in the engine's store under the engine's own name; `locate_model()`
will not find them, because they are not AnyInfer's to find. Which providers work this
way is declared on the descriptor. `anyinfer models pull ollama qwen3:8b` is the same
call from a shell.

## Where the Numbers Come From

Every hash, size, revision, and verification date in the catalog is read from the
upstream API by a pin script and written verbatim; an entry that cannot be verified is
not shipped. A weekly job re-checks every pinned file and every Ollama tag digest
against upstream and opens a human-reviewed pull request when something moved. A catalog
entry therefore either points at bytes that hash to what was recorded, or it fails
loudly.

!!! tip "Key Takeaways"
    - One catalog serves both "give me a default tier" and "show me what fits", and a
      user's pick bridges into the alias ladder with `with_alias_target()`.
    - Fit verdicts are five-state (`gpu`, `cpu`, `tight`, `no`, `unknown`) and always
      carry their reasons.
    - Acquisition chooses the quantization for the machine, checks disk space first,
      resumes after interruption, and registers nothing until every file verifies.
    - Verification is per-file against pinned or API-reported digests; unverified files
      are refused by default and marked unverified forever if allowed.

## See Also

<div class="anyinfer-see-also" markdown>

- [The local subsystem](local.md): hardware detection, tuning, and supervision.
- [Run a model locally](../guides/local-inference.md): the task walkthrough.
- [Capabilities and provenance](capabilities.md): how catalog data feeds capability
  assembly.

</div>
