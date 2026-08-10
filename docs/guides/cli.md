# Run a prompt from the shell

`anyinfer run` sends one prompt through the same path the library uses; routing,
fallback, structured output, telemetry; then exits. It is the shell-shaped way to reach
everything AnyInfer abstracts, without writing a script or starting a server.

```bash
anyinfer run "Explain TCP slow start." --config anyinfer.json --target ollama:qwen3:8b
```

The reply streams to stdout as it arrives.

## Getting a config file in the first place

`anyinfer init` writes one from what this machine can already do, so the first five
minutes end in a working call rather than in the configuration reference:

```bash
anyinfer init
```

```text
detected   Linux / x86_64, 32.0 GiB RAM, NVIDIA RTX 4070 (12.0 GiB)
probed     17 loopback endpoint(s), every one a provider default:
           http://127.0.0.1:11434, http://127.0.0.1:1234/v1, …
found      ollama at http://127.0.0.1:11434 (4 models)
found      anthropic, credential env://ANTHROPIC_API_KEY
recommend  medium -> ollama:qwen3:8b

wrote      anyinfer.json
wrote      starter.py

next       python starter.py
           anyinfer verify --config anyinfer.json
```

It discovers rather than guesses: a provider reaches the file only when a loopback
endpoint it declares answered a model listing, or a credential variable it names is set.
Detected keys are written as `env://` references, never values, so the generated file is
safe to commit, which `init` says once and then leaves your `.gitignore` alone.

| Flag | What it does |
|---|---|
| `--output PATH` | Write the configuration somewhere other than `anyinfer.json` |
| `--force` | Replace an existing configuration and starter |
| `--no-probe` | Contact nothing; report credential evidence only |
| `--keyring` | Also look in the OS credential vault (may prompt to unlock) |
| `-y`, `--yes` | Do not ask before writing, on a terminal |
| `--json` | Emit the findings and the decisions for a script |

`anyinfer doctor` reports the same hardware without writing anything, and points here
when no configuration exists yet.

## Instructions for a coding agent

`anyinfer agents-md` prints a short fragment describing how this library is actually
called; the call shape, the traps worth pre-empting, and the list of things not to
hand-roll; rendered from the installed version rather than from memory:

```bash
anyinfer agents-md >> AGENTS.md
anyinfer agents-md --config anyinfer.json --format claude > CLAUDE.md
```

It writes nothing itself; the redirect is yours, and so is the review. See
[coding agents](coding-agents.md).

## Pointing it at providers

`run` reads the same [shared config file](../reference/configuration.md#file-format)
the Python SDK and sidecar use, so one file drives all three:

```json
{
  "providers": [
    { "id": "ollama" },
    { "id": "anthropic", "api_key": "env://ANTHROPIC_API_KEY" }
  ],
  "default_route": ["ollama:qwen3:8b", "anthropic:claude-sonnet-5"]
}
```

With a `default_route` configured, `--target` becomes optional:

```bash
anyinfer run "Summarize the CAP theorem." --config anyinfer.json
```

`anyinfer providers` lists every registered provider and the fields each one needs.

## Where the prompt comes from

The prompt can be an argument, piped on stdin, or both; stdin is appended, which makes
the usual Unix shapes work:

```bash
anyinfer run "Say hello."                       < /dev/null   # argument only
cat notes.txt | anyinfer run                                  # stdin only
cat notes.txt | anyinfer run "Summarize this:"                # instruction, then body
```

Add a system prompt with `--system`, or continue an existing conversation with
`--messages`, a JSON file of `{"role", "content"}` objects:

```bash
anyinfer run "And in one sentence?" --messages history.json --config anyinfer.json
```

## Output modes

By default the text streams to stdout and nothing else does, so `run` composes:

```bash
anyinfer run "Name three primes." --config anyinfer.json > primes.txt
```

| Flag | Effect |
|---|---|
| *(default)* | Streams text to stdout as it is generated. |
| `--no-stream` | Waits for the whole reply, then prints it. |
| `--json` | Prints one object with the text, usage, timing, tool calls, and warnings. |
| `--stats` | Prints timing, token, and cost figures **to stderr**, leaving stdout clean. |
| `--show-reasoning` | Prints reasoning deltas to stderr, on models that emit them. |

Because `--stats` writes to stderr, redirecting stdout still gives you a clean file while
the figures stay on the terminal:

```bash
anyinfer run "Explain quicksort." --config anyinfer.json --stats > answer.txt
```

## Enforcing a JSON schema

Point `--schema` at a JSON Schema file and the reply is validated before you see it,
using the strongest mechanism the provider offers. Output is the validated JSON:

```bash
echo '{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}' > city.json
anyinfer run "Which city hosted the 2004 Olympics?" \
  --config anyinfer.json --schema city.json
```

A reply that will not validate raises an error rather than printing something malformed.
Allow bounded retries with `--repair N`:

```bash
anyinfer run "..." --config anyinfer.json --schema city.json --repair 2
```

Schema mode implies `--no-stream`: a JSON document cannot be validated until it is
complete.

### Attach images, documents, and audio

`run` collects attachment files at the CLI boundary and sends typed multimodal parts through
the same client path as the SDK and sidecar:

```console
anyinfer run "Summarize these inputs" --image diagram.png --document report.pdf --audio note.wav
```

Repeat a flag to attach multiple files. MIME types are inferred from filenames, inline
payload ceilings are checked before dispatch, and an adapter that cannot represent a part
fails explicitly instead of dropping it. See [multimodal inputs](../concepts/multimodal-inputs.md)
for provider coverage and unknown-budget behavior.

### Compare fixed targets with an arena

```console
anyinfer run "Classify this" --schema schema.json \
  --arena openai:gpt-5-mini,anthropic:claude-haiku-4-5 \
  --arena-strategy consensus --stats
```

`--dry-run` reports the arena call ceiling and summed cost range while making zero provider
calls. Named policies from the shared configuration use `--arena-name`. See
[arena runs](../concepts/arena.md) for selection and tool-loop semantics.

## Declaring tools

`--tool` takes a JSON file declaring one tool, and is repeatable:

```json
{
  "name": "get_weather",
  "description": "Look up the current weather for a city.",
  "parameters": {
    "type": "object",
    "properties": { "city": { "type": "string" } },
    "required": ["city"]
  }
}
```

```bash
anyinfer run "What is the weather in Boston?" \
  --config anyinfer.json --tool get_weather.json
```

**`run` never executes tools.** It reports what the model asked for; on stderr, or in
the `tool_calls` array under `--json`, and leaves the calling to you. Running a tool the
model chose is a decision a shell command should not make on your behalf; for an
automated call-and-respond cycle, use the [tool loop](tool-loop.md) in a script.

Use `--tool-choice` to require or forbid tool use (`auto`, `none`, `required`).

## Routing and fallback

`--route` names an ordered fallback chain and is repeatable. The first target that
succeeds wins, so a local-first setup with a hosted backstop is one line:

```bash
anyinfer run "Draft a commit message." --config anyinfer.json \
  --route ollama:qwen3:8b --route anthropic:claude-sonnet-5
```

`--route` overrides `--target`, since naming an ordered list is the more specific
instruction.

## Sampling and limits

```bash
anyinfer run "Write a haiku about latency." --config anyinfer.json \
  --temperature 0.9 --max-tokens 60 --stop "---" --timeout 30
```

`--reasoning` (`minimal`, `low`, `medium`, `high`) sets reasoning effort on models that
expose it. Parameters a provider does not support are dropped rather than rejected, and so
are parameters a *model* is known not to have; sending one that does nothing is the
failure mode that looks exactly like success. Every drop is reported as a warning.

## Costing a request before you send it

`--dry-run` reports what a request would spend and whether it fits, using the same budget
calculator the client holds the real request to, so this is not a second estimate of the
same thing:

```bash
cat report.md | anyinfer run "Summarize:" --config anyinfer.json \
  --target openai:gpt-4.1 --dry-run
```

```text
target            openai:gpt-4.1
input estimate    18432 tokens (floor 6912)
  messages         18401
  schema           31
context window    128000 (catalog)
output reserve    4096
input allowance   115712
remaining         97280
fits              yes
estimated cost    0.0138-0.0697 USD
```

Nothing is sent. Where a figure is not known it says so rather than guessing; an unknown
context window prints `unknown`, never a plausible default. `--json` emits the same
information for scripts.

## Checking a target actually works

`anyinfer verify` sends one tiny request and reports what came back; the thing a health
check cannot tell you, because a credential can be valid for a model listing and useless
for inference:

```bash
anyinfer verify ollama:qwen3:8b --config anyinfer.json
```

```text
ok        ollama:qwen3:8b
          412 ms, schema via grammar
```

With no target it checks every target in the configured route, and it exits non-zero if
any of them failed, so it works as a setup gate in a script:

```bash
anyinfer verify --config anyinfer.json || { echo "fix your config first"; exit 1; }
```

Failures distinguish *unreachable* from *reachable but wrong*, because those need
different fixes:

```text
FAILED    openai:gpt-5
          401 unauthorized (check the api_key for this provider)
answered  ollama:qwen3:0.6b
          the provider answered, but not in the requested shape: response was not JSON
```

`--json` emits the same information for scripts, including anything the provider reported
about [its own runtime](../concepts/capabilities.md#runtime-diagnostics).

A target known to reason gets a larger output budget for the probe than the ordinary
64 tokens. A thinking model spends the small budget on reasoning before it says anything,
and the truncated result reads as "the provider answered with empty text"; a connection
failure you do not have.

## Fitting a directory into a prompt

`anyinfer context` collects files, reduces them to a budget, and prints the envelope. The
collection happens here, in the CLI; walking a filesystem and deciding what is safe to
send is an application's job, and the library only reduces what it is handed.

```bash
anyinfer context src/ --query "how does credential resolution work?" --max-tokens 8000
```

The envelope goes to stdout so it can be piped; the account of what was dropped goes to
stderr so piping it does not silently discard that:

```text
tiered: 46 of 340 document(s); ~7900 of 8000 tokens; 12 collapsed; 282 omitted; limited by tokens
```

Vendored, generated, binary, and oversized files are skipped; pass `--include-generated` to
offer them anyway, and `--pin PATH` to force a file in ahead of the ranked candidates.

Give the budget with `--max-tokens`, or with `--target` to take it from that model's
context window. An unknown window is refused rather than guessed:

```text
the context window of 'openai-compat:mystery' is unknown, so there is no budget to reduce
against; pass --max-tokens to choose one yourself
```

### Choosing a strategy from measurements

`--plan` runs every deterministic strategy and reports what each *would* produce. It spends
no inference:

```bash
anyinfer context src/ --query "…" --max-tokens 3000 --plan
```

```text
corpus            13 document(s)
budget            3000 tokens

strategy          kept  omitted   tokens  complete  limited by
 whole>ranked        2       11     2192        no  tokens
 ranked              2       11     2192        no  tokens
*tiered              6        7     2893        no  tokens
 packed              4        9     2884        no  tokens

distill           141 chunk(s), 142+ generation call(s); the only strategy that spends money
```

`*` marks the recommendation. `whole>ranked` means the strategy could not do what was asked
and reports what it did instead; the same way `auto` does.

### Tuning

Every [advanced setting](../concepts/context-reduction.md#advanced-settings-in-one-place)
has a flag, and they read the `context` block of `--config` as their baseline:

```bash
anyinfer context src/ --query "…" --max-tokens 8000 --preset recommended
anyinfer context src/ --query "…" --max-tokens 8000 \
  --context-selection-order density --context-diversity 0.3 --context-query-expansion
```

Precedence is config file, then `--preset`, then individual flags. Boolean settings take a
`--no-` form, so `--no-context-collapse-duplicates` turns one off that the file or preset
turned on.

`--json` prints the machine-readable record instead of the envelope, for both modes.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The request succeeded. |
| `1` | The request failed; the error and its hint are on stderr. For `verify`, at least one target did not pass. |
| `2` | The command was used incorrectly; no prompt, no providers, bad flags. |
| `130` | Interrupted with `Ctrl-C`. |

## See also

<div class="anyinfer-see-also" markdown>

- [The sidecar](../serve/README.md): the long-running OpenAI-compatible service
- [Shared configuration](../reference/configuration.md)
- [Enforce a JSON schema](structured-output.md)
- [Run the tool loop](tool-loop.md)

</div>
