# Acquiring models

One path from *catalog pick* → *bytes on disk* → *a path an engine can be pointed at*.

```python
report = client.acquire_model("qwen2.5-7b-instruct", progress=on_progress)
report.plan.quantization  # 'Q5_K_M' — chosen for this machine, not assumed
report.entry.handle  # the file llama-server will be launched against
```

Two file shapes flow through one engine: a **GGUF** variant is a shard set whose handle is
the first shard, and a **Hugging Face snapshot** (for vLLM) is a directory whose handle is
the directory. What differs is the file list and the handle; resume, verification, locking,
cancellation, and progress accounting do not, and those are exactly the things that are
expensive to get right twice.

## The quantization is chosen, not assumed

Acquisition asks *which rung of this model's ladder can this machine actually run?* — the
highest-quality tier whose weights **and KV cache** fit the memory budget. A model that
exactly fills VRAM leaves nothing for the cache, and the server will not serve.

A rung that fits the accelerator beats a better rung that would only fit in system RAM:
Q4_K_M resident on a GPU is dramatically faster than Q8_0 paging through the CPU.

One policy is stated outright, and it is why the default ladder stops where it does:

> **Below Q4, prefer a smaller model at a good quantization over a bigger model at a bad
> one.**

So when nothing at Q4_K_M or better fits, acquisition refuses and tells you why, rather than
quietly handing you a two-bit quantization:

```
no curated quantization of 'qwen2.5-32b-instruct' fits this machine —
qwen2.5-32b-instruct-q8-0: needs 35.2 GiB (Q8_0 weights plus a 8192-token KV cache)
but only 15.6 GiB of VRAM is budgeted; …
```

Ask for it explicitly if you want it:

```python
from anyinfer import local

client.acquire_model("qwen2.5-32b-instruct", prefs=local.VariantPrefs(allow_low_quality=True))
```

For vLLM the ladder is a different shape with hard gates: FP8 kernels need NVIDIA compute
capability 8.9 or newer, the Marlin GPTQ kernel needs 8.0, AWQ needs 7.5. A driver that does
not report a capability *excludes* a gated variant rather than optimistically permitting it —
guessing there produces a download that fails at model load with a kernel error.

## Know the cost before you pay it

```python
report = await client.acquire_model("gpt-oss-120b", dry_run=True)

report.plan.total_bytes  # 63_387_346_208
report.plan.already_have_bytes  # what a previous interrupted run already fetched
report.plan.remaining_bytes  # what this run would actually transfer
```

Nothing is written. This is what an application needs to put a real confirmation dialog in
front of a sixty-gigabyte download instead of discovering the size afterwards.

Before any transfer starts, free disk space is checked against what remains plus ten percent.
Filling a user's disk with a download that fails at 98% is the worst available outcome and is
entirely avoidable.

## Progress is about the whole acquisition

```python
def on_progress(p):
    print(f"{p.fraction:.0%}  {p.filename}  [{p.file_index}/{p.file_count}]")
```

`AcquisitionProgress` reports aggregate figures, not per-file ones. A four-shard model whose
byte counter restarts at zero on every shard is worse than no progress bar at all, because a
user cannot tell a restart from a stall.

Three consequences worth knowing:

- **The total is known before the first byte arrives.** Sizes are pinned in the catalog, so a
  percentage is correct from 0%.
- **Bytes already on disk are counted.** Resuming a 90%-complete download reports 90%, not
  0%. `session_bytes` is the separate "what this run transferred" figure, and it is what rate
  and ETA are derived from.
- **Rate and ETA stay `None` until there is a real sample.** A wildly wrong ETA in the first
  second is worse than no ETA.

Callbacks are throttled to at most one per 250 ms or per 4 MB, whichever comes first — plus
an unconditional callback on every phase change and every file completion, so a UI can never
miss a state change.

The sink may be invoked from a worker thread. It **must not block, must not raise, and must
not call back into the client**. A sink that raises anyway is caught, recorded once as a
warning on the report, and then dropped for the rest of the run — a broken progress bar must
not fail a download.

## Interrupting is not deleting

Cancel an acquisition and the partial transfers stay on disk. Run it again and it resumes
from where it stopped. Nothing is registered until every file verifies, so a half-complete
model is invisible rather than half-usable.

## What gets verified, and what does not

| Where the file came from | What is checked |
|---|---|
| A pinned catalog artifact | The SHA-256 in the catalog. A mismatch is a hard failure. |
| A Hugging Face repository | The digest the API reports for that file, checked against the bytes. |
| A URL you supplied with a digest | Your digest. A mismatch is a hard failure. |
| A URL you supplied with no digest | **Refused**, unless you pass `allow_unverified=True`. |

Digests taken from an API are trust-on-first-use: we trust the API for *what the bytes should
be*, then verify the bytes against it. That is a real improvement over trusting the transfer,
and recording the digest turns a later upstream change into a detectable event rather than a
silent swap. An unverified file is recorded as unverified all the way out to
`locate_model()`, because "AnyInfer checked these bytes" and "AnyInfer found these bytes" are
different claims.

Two rules apply to every acquisition and are not optional:

- **File names from a remote API are treated as attacker-influenced input.** Absolute paths,
  `..` segments, drive letters, NUL bytes, and reserved Windows device names are rejected, and
  every destination is checked for containment *after* resolution so a symlink cannot escape.
- **Pickle-format weights are never fetched by default.** `*.bin`, `*.pt`, `*.pth`, and
  `*.ckpt` execute arbitrary code on load. When a repository publishes safetensors they are
  redundant; when it does not, acquisition fails with a hint naming the risk.

## Finding it again

```python
located = client.locate_model("qwen2.5-7b-instruct")

located.path  # a file for GGUF, a directory for a snapshot
located.verified  # whether every file was checked against a digest
located.launch_hints  # {'engine': 'llama.cpp', 'model': '…', 'ctx_size': 32768, …}
```

No network I/O, ever. Verification is the deliberate exception to "always check": re-hashing
forty gigabytes on every lookup would be absurd, so the rule is **verify on install and on
adoption; on later lookups compare size and modification time against the index, and re-hash
only on a mismatch**. Pass `verify=True` to force the full check.

`launch_hints` is **advisory data, not process control** — engine-shaped keys a caller turns
into arguments. For llama.cpp the supervisor consumes them automatically. For vLLM they are
what you would paste into a command line:

```python
hints = client.locate_model("qwen2.5-7b-instruct", engine="vllm").launch_hints
# {'engine': 'vllm', 'model': '/…/hf/qwen/…', 'quantization': 'awq',
#  'max_model_len': 32768, 'gpu_memory_utilization': 0.9}
```

AnyInfer acquires and locates vLLM weights; it does not start a vLLM process. Point a `vllm:`
preset target at the server you started with those arguments and it behaves like any other
target.

## Where things live

```
<model dir>/
  store.json                          the index
  gguf/<publisher>/<repo>/<sha12>/    a shard set
  hf/<publisher>/<repo>/<sha12>/      a repository snapshot
```

Revision-scoped directories mean two revisions of the same repository coexist, deletion is a
single tree removal, and two repositories shipping `model-00001-of-00004.safetensors` cannot
collide. The default location follows your platform's data directory; `ANYINFER_MODEL_DIR`
or `Client(model_dir=...)` overrides it.

`store.json` is a **cache, not the truth**. A user will eventually delete a directory by
hand, so every read tolerates a missing or corrupt index, and `rebuild_index()` recovers by
rescanning.

Two kinds of pre-existing files are adopted rather than re-downloaded:

- **Flat-layout GGUFs** from earlier AnyInfer builds, adopted where they lie, but only after
  verifying each against its catalog hash, so adoption is never a lie about the bytes.
- **Directories another tool owns**, registered as *external*: never written to, and never
  deleted by `remove_model()`, which only unregisters them.

Nothing here evicts anything. `disk_usage()` and `remove_model()` give an application what it
needs to build a policy; automatically deleting a forty-gigabyte download a user paid
bandwidth for is not a decision a library should make.

## Engines that keep their own store

Everything above is about weights **this library** fetches, places, verifies, and indexes.
Some local engines already have all of that — a store, a registry, a downloader, and for
those the useful operation is not *download these bytes* but *make yourself ready*:

```python
report = client.pull_model("ollama", "qwen3:8b")

report.already_present  # True when nothing had to move
report.bytes_transferred
```

Progress arrives as the same `DownloadProgress` telemetry a catalog acquisition emits, with
Ollama's per-layer counts accumulated into the whole-transfer figures that event promises.
`anyinfer models pull ollama qwen3:8b` is the same call from a shell.

The distinction is worth keeping in mind: those bytes land in **the engine's** store under
the engine's own name. Nothing is written to AnyInfer's model store, nothing is indexed, and
`locate_model()` will not find it, because it is not ours to find. Which providers work
this way is declared on the descriptor, so a UI can ask the registry rather than
special-casing engines.

## Next

- [The model catalog](catalog.md): what exists, and what fits.
- [Choose and download a local model](../guides/local-models.md): the task walkthrough.
