# Run a model locally

From a bare machine to a generated answer without installing or operating a separate
model daemon. AnyInfer shows what this machine can run, downloads and hash-verifies the
weights, fetches a pinned `llama-server` runtime after an explicit install command, and
supervises the server from the application process.

## 1. See what this machine can run

The [model catalog](../concepts/catalog.md) classifies every entry against detected
hardware:

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

`view.entries` includes models that will not fit, classified `no`. Use `view.runnable`
to show only the plausible ones, and `view.entries` when a user asked to see everything.

The same thing from a terminal:

```console
$ anyinfer models list --best-at coding
$ anyinfer models list --all --json
```

`anyinfer doctor` prints the detected hardware and a recommended tier without writing
anything. [Hardware detection](../concepts/local.md#hardware-detection-is-advisory)
never raises; anything it could not determine stays unknown rather than becoming a
guess. When the engine runs on a different machine, detection describes the wrong
computer — see
[when the model runs somewhere else](../concepts/catalog.md#when-the-model-runs-somewhere-else)
for supplying that host's specifications.

## 2. Check the cost before committing

Large models are large. Ask what a download would take before starting it:

```python
plan = client.acquire_model("qwen2.5-coder-14b-instruct", dry_run=True).plan

print(f"{plan.quantization}: {plan.total_bytes / 1024**3:.1f} GB")
print(f"already on disk: {plan.already_have_bytes / 1024**3:.1f} GB")
```

Nothing is written. This is what a confirmation dialog should be built on.

The quantization is a result, not an input: the highest-quality rung that fits this
machine's memory budget. [The catalog](../concepts/catalog.md#acquiring-a-pick) gives
the rule and how to override it.

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

The percentage is correct from the first callback, counts anything already on disk, and
never goes backwards across shards. Interrupt it and nothing is lost: partial transfers
are kept, and running the same call again resumes rather than restarting.

```console
$ anyinfer models add qwen2.5-coder-14b-instruct
$ anyinfer models add qwen2.5-coder-14b-instruct --dry-run
$ anyinfer models add qwen3-32b --variant qwen3-32b-q6-k
```

## 4. Install a runtime

```console
$ anyinfer runtime list
$ anyinfer runtime install
```

The default is the small CPU, Metal, or Vulkan variant appropriate for this machine.
Archives are pinned and hash-verified, and no background service is installed; the step
is explicit because runtime downloads can be large. CUDA is a separate, much larger
opt-in that AnyInfer never installs on its own:

```console
$ anyinfer runtime install cuda
```

which refuses, before downloading anything, if the driver or GPU is too old for the
pinned build. When more than one runtime is installed, llama.cpp selects the best usable
backend by default; pin one for a provider instance with `options={"runtime": "cuda"}`,
or point at your own build with `options={"binary": "/custom/llama-server"}`.

## 5. Generate

```python
result = client.generate(
    "Write a Python function that reverses a linked list.",
    target="llama-cpp:qwen2.5-coder-14b-instruct-q4-k-m",
)
```

That single call resolves the artifact, downloads and verifies it if step 3 did not,
tunes a server plan for the hardware, starts `llama-server` on loopback, waits for
readiness, and answers. Later calls reuse the running server. How the plan is tuned —
postures, memory budgets, the KV cache — belongs to
[the local subsystem](../concepts/local.md#tuning-explains-itself); pass
`options={"posture": "conservative"}` on the provider settings to change it.

`client.models("llama-cpp")` lists only models registered in the local store, and
`client.locate_model()` finds a downloaded file again without network I/O; see
[finding it again](../concepts/catalog.md#finding-it-again). A tier alias such as
`target="medium"` resolves through the same catalog, and a user's pick can become that
default — see
[using a pick as your default tier](../concepts/catalog.md#using-a-pick-as-your-default-tier).

## Ollama instead

If you already run Ollama, it needs no supervision at all:

```python
client = ai.Client([ai.ProviderSettings.of("ollama")])
result = client.generate(prompt, target="ollama:qwen3:8b")
```

Ollama gives you grammar-enforced structured output and per-phase timings; llama-cpp
gives you control over tuning and the exact model file. Either way it is one target
string.

## Troubleshooting

**`could not find llama-server on PATH`** — run `anyinfer runtime install`, install a
llama.cpp build on `PATH`, or pass `options={"binary": "/path/to/llama-server"}`.

**`needs about 40.0 GiB but only 8.0 GiB of VRAM is uncommitted`** — admission control
refused before spawning, so nothing crashed. Choose a smaller tier or a more
conservative posture.

**`llama-server exited with code 3 while loading`** — the error includes the server's
own log tail, which usually names the real cause (an incompatible quantization, a
corrupt file, or genuine memory exhaustion).

**A model unloads while you are still reading its output** — it should not: the idle
timer keys on active streams, not on when the last request arrived. If you see this,
please report it.

!!! tip "Key takeaways"
    - `local_catalog()` classifies every catalog entry against this machine, best fit
      first, with the reasons attached.
    - A `dry_run=True` acquisition prices the download without writing anything, and a
      real one resumes after interruption.
    - Runtime installs are explicit, pinned, and hash-verified; CUDA is a separate
      opt-in that is refused when the driver or GPU is too old.
    - One `generate()` against a `llama-cpp:` target acquires, tunes, supervises, and
      answers; later calls reuse the running server.

## See also

<div class="anyinfer-see-also" markdown>

- [The local subsystem](../concepts/local.md): detection, tuning, and supervision.
- [The model catalog](../concepts/catalog.md): fit levels, verification, and the store.
- [Quickstart](quickstart.md): the first working call, local or hosted.

</div>
