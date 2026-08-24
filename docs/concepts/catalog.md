# The model catalog

Two questions, two shapes over the same data:

- *"Just give me a good default."* → the **tier ladder**: `small`, `medium`, `large`.
- *"Let me see what I could run."* → the **model catalog**: forty-odd curated local models,
  each annotated with whether your machine can actually run it.

They are bridged, not merged. A user's pick from the catalog flows *into* the ladder rather
than around it, so an application can offer both without maintaining two code paths.

## What is in it

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

Each entry carries a **quantization ladder** — the same model at Q8_0, Q6_K, Q5_K_M, and
Q4_K_M, because "which model" and "at what quality" are different questions, and the second
one depends on your hardware:

```python
for variant in entry.variants_for("llama.cpp"):
    print(variant.quantization, variant.est_file_bytes)
# Q8_0   8.10 GB
# Q6_K   6.25 GB
# Q5_K_M 5.44 GB
# Q4_K_M 4.68 GB
```

### One model, two distribution channels

Most models are published both as a pinned GGUF file set (for the supervised llama.cpp path)
and as an Ollama registry tag. The catalog records per-channel availability rather than
keeping two parallel lists:

- **GGUF**: a repository, an immutable commit, named files, and a SHA-256 per file.
  AnyInfer downloads and verifies these itself.
- **Ollama**: a tag. The Ollama daemon owns its own blob store, so AnyInfer never places
  files for it; the tag is what gets recommended, and its manifest digest is recorded so a
  moved tag is detectable.

### Chat models and embedding models

Every row states its `kind`: `"generation"` (the default) or `"embedding"`. Both kinds are
acquired identically — a GGUF is a GGUF, and the download, hashing, and verification
machinery never cares what the weights compute — so they share one table rather than
splitting into two that would drift.

What differs is everything downstream of acquisition, and it differs enough that the
distinction is worth stating:

- An embedding row carries `dimensions` and `max_input_tokens`, the two facts a model card
  actually publishes about its vectors. They reach `client.compare_embedding()` and the
  capability system the same way a hosted provider's declared limits do.
- Its memory estimate is computed from its own architecture and sequence length, not from
  the chat-model KV table — that table's smallest rung is a thousand times larger than an
  embedding model, and taking its default would budget gigabytes for something that needs
  megabytes.
- It reports no chat features and only the `embedding` operation, so
  `client.models(operation="embedding")` finds it and a chat request never routes to it.
- It is **not** part of the `small`/`medium`/`large` ladder. Those tiers answer "how big a
  chat model should I run", a question an embedding model has no answer to, and the catalog
  validator refuses an alias that points at one.

```python
for entry in catalog.models_for(kind="embedding"):
    print(entry.id, entry.embedding.dimensions)
```

Passing no `kind` keeps every row: a caller browsing what a machine can run wants the
embedding models too. A chat picker asks for `kind="generation"` explicitly rather than
relying on a narrowing it never requested.

### Categories are a closed vocabulary

`best_at` is drawn from a fixed set — `general-chat`, `coding`, `reasoning`, `vision`,
`long-context`, and nine others. Closed on purpose: a free-text tag set drifts into synonyms
nobody can filter on.

```python
for entry in catalog.models_for("llama-cpp", best_at="coding"):
    print(entry.id)
```

## Will it run?

Browsing without a fit answer is just a list. `local_catalog()` classifies every entry
against your machine:

```python
view = client.local_catalog("llama-cpp", best_at="coding")

for entry in view.runnable:
    print(entry.model.id, entry.fit.level, entry.fit.reasons[0])
```

Five levels, every one of them with reasons attached:

| Level | Meaning |
|---|---|
| `gpu` | Fits comfortably in the accelerator's memory budget. |
| `cpu` | Too large for the GPU, but fits in system RAM. Runs, more slowly. |
| `tight` | Fits, with little room left for a longer context. |
| `no` | Exceeds this machine's memory entirely. |
| `unknown` | The numbers needed to judge are not available. |

Entries come back best-fit-first, and the ordering is deterministic — a browsing UI that
reshuffles between calls is unusable.

`reasons` is not decoration. "Why did it say tight?" has to be answerable from the returned
object alone:

```python
entry.fit.reasons
# ('needs 8.4 GiB of VRAM against a 9.0 GiB budget — it fits, but with little room
#   for a longer context',
#  'planning for the vulkan runtime; installing the CUDA runtime would give better
#   throughput on this NVIDIA device')
```

## When the model runs somewhere else

Ollama can point at another machine. Probing *this* machine then describes the wrong
computer, and no Ollama API reports its host's specifications, so AnyInfer says so instead
of guessing:

```python
view = await client.local_catalog("ollama")

if view.hardware_source == "unavailable":
    # Ask the user for the remote host's specs — the library has no UI and will not prompt.
    ...
```

Feed the answer back in, and the fits become real:

```python
from anyinfer import local

specs = local.HardwareProfile.from_user_input(ram_gb=64, vram_gb=24, accelerator="cuda")
view = await client.local_catalog("ollama", hardware=specs)

view.hardware_source  # 'provided'
view.notes  # ('fits are based on specs you provided, not measured', ...)
```

Values arrive in gigabytes because that is what a user reads off a spec sheet, and anything
omitted stays unknown rather than becoming zero.

A remote engine is also not free. An Ollama daemon on someone else's host may sit behind a
metered proxy, so its per-token cost is reported as *unknown* rather than the genuine zero a
loopback engine gets.

## Using a pick as your default tier

The bridge between the two shapes is one call:

```python
catalog = load_default_catalog().with_alias_target("medium", "llama-cpp", "qwen2.5-14b-instruct")
client = ai.Client(providers=[...], catalog=catalog)

client.generate(prompt, target="medium")  # now resolves to the user's pick
```

The result is an ordinary catalog: alias resolution is unchanged, and the original is
untouched — overlays produce new catalogs rather than mutating shared ones.

Applications can also overlay their own models wholesale, per model id, the same way they
overlay aliases. That is the supported route for models the bundled catalog deliberately
excludes — anything under non-commercial or research-only terms, which stay out so that
"AnyInfer recommended it" remains legally clean.

## Where the numbers come from

Every hash, size, revision, and verification date in the catalog is read from the upstream
API by a pin script and written verbatim. Nothing in the file is hand-typed, and an entry
that cannot be verified is not shipped rather than shipped half-pinned. A weekly job
re-checks every pinned file and every Ollama tag digest against upstream and opens a
human-reviewed pull request when something moved.

The practical consequence: a catalog entry either points at bytes that exist and hash to
what we recorded, or it fails loudly and detectably. It never silently points at different
weights than the ones it was verified against.

## Next

- [Acquiring models](models.md): downloading a pick, and finding it again later.
- [Choose and download a local model](../guides/local-models.md): the task walkthrough.
- [The local subsystem](local.md): hardware, runtimes, tuning, and supervision.
