# Run a prompt from the shell

`anyinfer run` sends one prompt through the same path the library uses — routing,
fallback, structured output, telemetry — then exits. It is the shell-shaped way to reach
everything AnyInfer abstracts, without writing a script or starting a server.

```bash
anyinfer run "Explain TCP slow start." --config anyinfer.json --target ollama:qwen3:8b
```

The reply streams to stdout as it arrives.

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

The prompt can be an argument, piped on stdin, or both — stdin is appended, which makes
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

**`run` never executes tools.** It reports what the model asked for — on stderr, or in
the `tool_calls` array under `--json` — and leaves the calling to you. Running a tool the
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
expose it. Parameters a provider does not support are dropped rather than rejected, and
the drop is reported as a warning.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The request succeeded. |
| `1` | The request failed; the error and its hint are on stderr. |
| `2` | The command was used incorrectly — no prompt, no providers, bad flags. |
| `130` | Interrupted with `Ctrl-C`. |

## See also

<div class="anyinfer-see-also" markdown>

- [The sidecar](../serve/README.md) — the long-running OpenAI-compatible service
- [Shared configuration](../reference/configuration.md)
- [Enforce a JSON schema](structured-output.md)
- [Run the tool loop](tool-loop.md)

</div>
