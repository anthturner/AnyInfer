# Choose and download a local model

Browse what you could run, pick one, download it with a progress bar, and run it — without
guessing at quantizations or hunting for files afterwards.

If you already know which model you want and just want it served,
[run a model locally](local-inference.md) is the shorter path.

## 1. See what this machine can run

```python
import anyinfer as ai

client = ai.Client([ai.ProviderSettings.of("llama-cpp")])

view = client.local_catalog("llama-cpp", best_at="coding")
for entry in view.runnable:
    size = entry.model.est_file_bytes / 1024**3
    print(f"{entry.model.id:<32} {size:5.1f} GB  {entry.fit.level}")
```

```
qwen2.5-coder-7b-instruct          4.4 GB  gpu
qwen2.5-coder-14b-instruct         8.4 GB  tight
qwen2.5-coder-32b-instruct        18.5 GB  cpu
devstral-small                    13.3 GB  cpu
```

Entries come back best-fit-first, and every one carries its reasoning:

```python
entry = view.entries[0]
print(entry.fit.reasons[0])
# needs 5.3 GiB of VRAM; 15.6 GiB is budgeted at the balanced posture
```

`view.entries` includes models that will not fit, classified `no`. Use `view.runnable` to
show only the plausible ones, and `view.entries` when a user asked to see everything.

The same thing from a terminal:

```console
$ anyinfer models list --best-at coding
$ anyinfer models list --all --json
```

## 2. Check the cost before committing

Large models are large. Ask what a download would take before starting it:

```python
plan = client.acquire_model("qwen2.5-coder-14b-instruct", dry_run=True).plan

print(f"{plan.quantization}: {plan.total_bytes / 1024**3:.1f} GB")
print(f"already on disk: {plan.already_have_bytes / 1024**3:.1f} GB")
```

Nothing is written. This is what a confirmation dialog should be built on.

Note that the quantization is a *result*, not an input: it was chosen as the highest-quality
rung that fits this machine's memory budget. See
[acquiring models](../concepts/models.md) for the rule and how to override it.

## 3. Download it

```python
def show(progress):
    if progress.fraction is not None:
        rate = progress.bytes_per_second or 0
        print(
            f"\r{progress.fraction:5.0%}  {rate / 1024**2:5.1f} MiB/s  "
            f"[{progress.file_index}/{progress.file_count}] {progress.filename}",
            end="",
        )


report = client.acquire_model("qwen2.5-coder-14b-instruct", progress=show)
print(f"\n{report.plan.quantization} at {report.entry.handle}")
```

The percentage is correct from the first callback, counts anything already on disk, and never
goes backwards across shards.

Interrupt it and nothing is lost: partial transfers are kept, and running the same call again
resumes rather than restarting.

```console
$ anyinfer models add qwen2.5-coder-14b-instruct
$ anyinfer models add qwen2.5-coder-14b-instruct --dry-run
$ anyinfer models add qwen3-32b --variant qwen3-32b-q6-k
```

## 4. Run it

The llama.cpp adapter finds what you downloaded, so a target string is all it takes:

```python
result = client.generate(
    "Write a Python function that reverses a linked list.",
    target="llama-cpp:qwen2.5-coder-14b-instruct-q4-k-m",
)
```

`client.models("llama-cpp")` likewise lists only models registered in the local store.
Browse `client.local_catalog("llama-cpp")` when you want the larger set that can be
downloaded; catalog availability is not presented as installed inventory.

If no runtime is installed yet, ask for the small one:

```console
$ anyinfer runtime list
$ anyinfer runtime install
```

AnyInfer never installs the CUDA runtime by itself — it is several hundred megabytes, and
that is a decision a user makes. On an NVIDIA machine the catalog will say so:

```console
$ anyinfer runtime install cuda
```

which refuses, before downloading anything, if the driver or GPU is too old for the pinned
build.

## 5. Find it later

```python
located = client.locate_model("qwen2.5-coder-14b-instruct")
print(located.path)  # no network I/O
print(located.launch_hints)  # {'engine': 'llama.cpp', 'ctx_size': 32768, …}
```

```console
$ anyinfer models installed
$ anyinfer models where qwen2.5-coder-14b-instruct
$ anyinfer models rm gguf-qwen-qwen2.5-coder-14b-instruct-gguf-3f2a1c8d9e01
```

Removal is explicit. Nothing evicts anything automatically — deleting a download a user paid
bandwidth for is not a decision a library should make.

## Serving a model from another machine

Point Ollama at a remote host and AnyInfer stops pretending it knows the hardware:

```python
client = ai.Client([ai.ProviderSettings.of("ollama", base_url="http://192.168.1.50:11434")])

view = client.local_catalog("ollama")
view.hardware_source  # 'unavailable'
```

Ask the user for the host's specifications and pass them back:

```python
from anyinfer import local

specs = local.HardwareProfile.from_user_input(ram_gb=64, vram_gb=24, accelerator="cuda")
view = client.local_catalog("ollama", hardware=specs)

view.hardware_source  # 'provided'
```

The fits are now real, and `view.notes` says they came from supplied specifications rather
than measurement.

## Using your pick as a default tier

```python
catalog = ai.load_default_catalog().with_alias_target(
    "medium", "llama-cpp", "qwen2.5-coder-14b-instruct"
)
client = ai.Client([ai.ProviderSettings.of("llama-cpp")], catalog=catalog)

client.generate("…", target="medium")
```

## What to read next

- [The model catalog](../concepts/catalog.md): fit levels, channels, and categories.
- [Acquiring models](../concepts/models.md): verification, resume, and the store layout.
- [Run a model locally](local-inference.md): tuning, supervision, and admission control.
