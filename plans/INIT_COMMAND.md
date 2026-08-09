# `anyinfer init` — zero to a working configuration

**Scope:** one command that inspects the machine, finds what is already usable, and
writes a valid `anyinfer.json` plus a runnable starter script. **Goal:** the first five
minutes with this library end in a working call rather than in the configuration
reference. **Non-goal:** an interactive TUI, a credential manager, or anything that
installs software. `init` *discovers and writes*; `models add` and `runtime install`
already own acquisition.

**Audience for this plan:** contributors editing the existing files directly. Code audit
is as of **2026-08-09**; re-verify before starting each task.

**Authority:** DESIGN.md §2 (goal 5, novice-friendly aliases), §12 (local subsystem),
§15 (configuration and credentials), §19 (M5 shared configuration); ADR-008 (descriptors
are declarative — no per-engine branches in this command either).

**Governance intent:** no ADR needed. This composes existing public APIs behind a new CLI
verb, inside the CLI workstream boundary (AGENTS.md: the CLI "delegates inference,
reduction, and config semantics to public core APIs"). Two additions do reach into the
core and need review: a **config writer** (§3.3) and one new declarative
`SetupField` attribute (§3.2).

---

## 1. Motivation and evidence

Everything `init` needs already exists, and nothing composes it:

| Fact needed | Where it lives today |
|---|---|
| Hardware, accelerators, RAM/VRAM | `anyinfer.local.detect()` → used by `_doctor` ([cli.py:790](../src/anyinfer/cli.py#L790)) |
| Which tier fits this machine | `recommend_alias()` ([local/recommend.py:73](../src/anyinfer/local/recommend.py#L73)) |
| Which providers exist and what they need | `ProviderRegistry` + `ProviderSetupSpec` ([registry.py:201](../src/anyinfer/registry.py#L201)) |
| Whether a target actually answers | `anyinfer verify` ([cli.py:843](../src/anyinfer/cli.py#L843)) |
| What a valid config looks like | `load_config` / `AnyInferConfig` ([config/__init__.py:55](../src/anyinfer/config/__init__.py#L55)) |

The verbs are `run`, `verify`, `benchmark`, `doctor`, `providers`, `models`, `runtime`,
`context`, `config`, `tools`, `serve`. The missing one is the *first* one. Today a new
user runs `doctor`, reads a tier alias, then hand-writes JSON against the configuration
reference to use it — a documentation-mediated step between "I installed this" and "it
works", which is exactly where a batteries-included library is judged.

There is also an asymmetry worth closing: the library can *read* the shared config format
from three frontends but cannot *write* it, so every example of the format is prose.

## 2. What `init` does

```
$ anyinfer init
detected   Windows 11 / x86_64 · 32 GiB RAM · NVIDIA RTX 4070 (12 GiB)
found      ollama at http://127.0.0.1:11434 (4 models)
found      ANTHROPIC_API_KEY in the environment
recommend  medium → ollama:qwen3:8b

wrote      anyinfer.json
wrote      example.py

next       python example.py
           anyinfer verify --config anyinfer.json
```

Rules that keep it honest:

- **Never overwrite.** An existing `anyinfer.json` stops the command with a hint
  (`--force` to replace, `--output` to write elsewhere). Destructive-by-default is not
  acceptable for a file a user may have hand-tuned.
- **Never write a secret.** A detected key becomes `"api_key": "env://ANTHROPIC_API_KEY"`
  — the reference, never the value. This is the credential resolver's existing contract
  ([credentials/resolver.py:8](../src/anyinfer/credentials/resolver.py#L8)) and it is the
  single most important property of the generated file, since that file gets committed.
- **Never claim what it did not check.** A provider is written into the config only if it
  was *observed* (endpoint answered, or the environment variable is present and
  non-blank). Nothing is added speculatively.
- **Never install.** If nothing local is running and no key is present, `init` still
  writes a valid file, comments the next step, and points at `anyinfer models add`.

## 3. Design

### 3.1 Discovery, driven by descriptors

New module `src/anyinfer/local/discover.py` (local subsystem, because "what is running on
this machine" is its subject):

```python
@dataclass(frozen=True, slots=True)
class DiscoveredProvider:
    """A provider found usable on this machine, and the evidence for it."""

    provider_id: str
    base_url: str | None
    evidence: Literal["endpoint", "environment", "credential-store"]
    detail: str                      # "4 models", "ANTHROPIC_API_KEY set"
    models: tuple[str, ...] = ()


async def discover(registry: ProviderRegistry, *, timeout_s: float = 1.5) -> tuple[DiscoveredProvider, ...]
```

Endpoint probing iterates descriptors whose `locality == "local"` and that declare a
`default_base_url`, then calls the adapter's existing `health()` / `list_models()` —
the adapter contract, unchanged, with a short timeout and every failure swallowed into
"not found". No provider-specific probing code, no `if provider == "ollama"`.

### 3.2 One new declarative field

Environment detection must not parse prose. Today the convention lives inside
`SetupField.placeholder` as free text — `"env://ANTHROPIC_API_KEY or a literal key"`
([providers/anthropic.py:482](../src/anyinfer/providers/anthropic.py#L482)). Add a
declarative sibling on `SetupField`:

```python
env_var: str = ""
"""Environment variable this field is conventionally supplied from, if any."""
```

Populate it for every descriptor that names one in its placeholder today (Anthropic,
Azure, Bedrock, OpenAI, Gemini, and the presets that declare keys). Placeholders stay as
they are — they are UI hints; this is machine-readable fact. This is the ADR-008-shaped
answer: extend the setup spec so consumers stay generic.

*This field is also what a config UI needs to say "we found this in your environment",
so it pays for itself beyond `init`.*

### 3.3 A config writer

`anyinfer.config` gains the missing half:

```python
def dumps_config(config: AnyInferConfig, *, comments: bool = False) -> str
def dump_config(config: AnyInferConfig, path: Path, *, force: bool = False) -> None
```

Round-trip is the contract: `loads_config(dumps_config(c)) == c` for every configuration
the loader accepts. `comments=True` emits a JSON file with a leading `"_comment"` key
rather than JSONC — the format is JSON, and `init` must not write something the loader
would reject.

### 3.4 Starter script

`example.py` is generated from a template with the resolved default target substituted.
It must be one of the examples that already runs in CI, so a generated starter cannot
drift from a working one — the doc-examples rule
([tests/test_docs_examples.py](../tests/test_docs_examples.py)) applies.

## 4. Tasks

**IN.1 — `SetupField.env_var`.** Add the field; populate across built-in descriptors and
[presets.py](../src/anyinfer/providers/presets.py). *Acceptance:*
`tests/test_registry_and_catalog.py` asserts every descriptor whose placeholder mentions
`env://` also declares `env_var`, so the two never drift.

**IN.2 — `discover()`.** New `local/discover.py`. Bounded timeout, concurrent probes,
total failure tolerated. *Acceptance:* `tests/test_local_discover.py` uses a scripted
provider (`anyinfer.testing.ScriptedProvider`, shipped) to prove: endpoint found; endpoint refused →
absent; slow endpoint → timed out, not hung; env var present → reported without reading
its value into the result.

**IN.3 — config writer.** `dumps_config` / `dump_config` in
[config/__init__.py](../src/anyinfer/config/__init__.py), exported from `__all__`.
*Acceptance:* property-style round-trip test over the fixtures already in
`tests/test_config.py`; writing to an existing path without `force` raises `ConfigError`
with a hint.

**IN.4 — the verb.** `_init` in [cli.py](../src/anyinfer/cli.py) plus its subparser;
flags `--output`, `--force`, `--json`, `--no-probe`, `--yes`. Terminal presentation
follows `_doctor`'s aligned two-column style. *Acceptance:* `tests/test_cli_init.py`
covers: nothing found (still writes a valid file); one local engine found; an env key
found (written as `env://`, never the value); existing file refused.

**IN.5 — starter script generation.** Template lives beside the runnable examples, not
inline in `cli.py`. *Acceptance:* the generated script is byte-identical to the checked-in
example modulo the target string, and CI executes that example.

**IN.6 — `doctor` cross-link.** `doctor` ends with "run `anyinfer init` to write this as
configuration" when no config file is present. One line, no behaviour change.

**IN.7 — docs.** Rewrite the opening of
[docs/guides/quickstart.md](../docs/guides/quickstart.md) to lead with `init`; update
[docs/guides/cli.md](../docs/guides/cli.md) and
[docs/reference/configuration.md](../docs/reference/configuration.md) (the writer is part
of the configuration contract). README "Try it without credentials" gains the two-command
path.

## 5. Testing

`tests/test_cli_init.py` and `tests/test_local_discover.py`. All probing in tests goes
through in-process transports — no test may open a socket to a real port, including
`127.0.0.1:11434`, since a developer machine running Ollama would otherwise make the
suite non-deterministic. `filterwarnings = ["error"]` applies to the concurrent probe
path; ensure every probe client is closed.

## 6. Risks

- **R-IN1 — a secret in a committed file.** The one unacceptable failure. Mitigate: the
  writer has no code path that emits a resolved credential; a test asserts a fake
  registered secret never appears in `dumps_config` output; redaction covers the printed
  summary too.
- **R-IN2 — probing surprises.** Touching loopback ports uninvited can look like scanning
  behaviour to a security-conscious user. Mitigate: only descriptor-declared default
  endpoints, only loopback, `--no-probe` opt-out, and the summary names every endpoint it
  contacted.
- **R-IN3 — generated config rot.** A written file pins today's shape. Mitigate:
  `format_version` is already in the format and the writer emits it.

## 7. Decisions (2026-08-09)

1. **`init` prints one line about `.gitignore` and writes nothing.** The generated config
   holds only `env://` references, so it is safe to commit — which is worth saying once,
   in the summary, and is not worth editing a file the user did not name. Editing repo
   hygiene files uninvited is the kind of helpfulness that gets a tool distrusted.
2. **Keyring discovery is `--keyring` only.** An environment variable is already in this
   process; the OS vault is not, and reading it can prompt for unlock. Environment
   evidence is free to collect, vault evidence is asked for. When `--keyring` is passed
   and the `[keyring]` extra is absent, the flag errors with the install hint rather than
   silently finding nothing.
