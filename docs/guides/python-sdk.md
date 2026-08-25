# Integrate the Python SDK

Use the SDK when AnyInfer runs inside a Python application.
[Quickstart](quickstart.md) is the fastest path to a first result; this page is the
reference for embedding the SDK properly: the client lifecycle and the error handling a
long-lived application needs.

## Configure the Client

For deployed applications, keep provider identity and routing in the
[shared configuration file](../reference/configuration.md):

```python
import anyinfer as ai

config = ai.load_config("anyinfer.json")

with ai.Client(config.providers, route=config.route) as client:
    result = client.generate("Give me a two-sentence status summary.")
    print(result.text)
```

For a small script, construct the same settings directly:

```python
providers = [
    ai.ProviderSettings.of(
        "anthropic",
        api_key="env://ANTHROPIC_API_KEY",
    )
]

with ai.Client(providers) as client:
    result = client.generate("Hello", target="anthropic:claude-sonnet-4-5")
```

Credential references are resolved when an adapter is first used and registered for
redaction. Prefer `env://` or `credential://` references to literals in source code and
configuration files.

## One Client, Reused, Then Closed

`AsyncClient` is the native implementation. `Client` is its thread-safe synchronous
facade; both accept the same arguments and return the same domain types.

=== "Async"

    ```python
    async with ai.AsyncClient(config.providers, route=config.route) as client:
        result = await client.generate("Explain the result.")
    ```

=== "Sync"

    ```python
    with ai.Client(config.providers, route=config.route) as client:
        result = client.generate("Explain the result.")
    ```

Choose `AsyncClient` inside an async application and `Client` in a synchronous one.
Create one client and reuse it; do not create one per request. Since a client owns
connection pools and any supervised local servers, close it with a context manager or an
explicit `close()`/`aclose()` call. One client serves many conversations; continuity
across turns is a [session](../concepts/sessions.md) concern, not a client-lifecycle
one.

`generate()` returns the finished result; to consume events as they arrive, see
[streaming](streaming.md).

## Shape the Sampling

`Sampling` carries every knob that changes *how* the model chooses tokens. Every field
defaults to unset, and unset means the provider's own default — AnyInfer never invents a
temperature, and an unset field is omitted from the wire request entirely.

```python
result = client.generate(
    "Summarize this changelog.",
    sampling=ai.Sampling(
        temperature=0.2,
        max_output_tokens=400,
        seed=1234,
        frequency_penalty=0.3,
    ),
)
```

`seed` asks the provider to make a repeated identical request more likely to produce
identical output. Treat it as best-effort: every provider that ships the field documents
it that way, and none promise reproducibility across model revisions.

Not every target has every knob. A provider that cannot honor one emits a
[`ParameterDropped`](../concepts/telemetry.md) event naming the parameter and what the
target did instead — the point being that a request accepted and quietly ignored looks
exactly like one that worked.

## Ask for Token Probabilities

`logprobs` asks for the model's confidence in what it produced: `0` for each chosen
token's own log-probability, a positive count for that many alternatives beside it.

```python
result = client.generate("Classify: positive or negative?", logprobs=3)

for token in result.logprobs:
    alternatives = ", ".join(f"{alt.token}={alt.probability:.2f}" for alt in token.top)
    print(f"{token.token!r} p={token.probability:.2f}  ({alternatives})")
```

Each `TokenLogprob` carries the natural-log value the provider reported, with
`probability` available when a linear scale reads better. Targets that do not report
probabilities are not silently answered without them: the parameter is reported dropped,
the same as any other unhonored request field.

## Ask for Attributions

When a request supplies documents, `cite_documents=True` asks the target to say which of
them each part of its answer came from:

```python
result = client.generate(
    grounded_messages,
    cite_documents=True,
)

for citation in result.citations:
    supported = citation.span_of(result.text)
    print(f"{supported!r} ← {citation.title or citation.uri}")
```

It is off by default and never inferred from the mere presence of a document: every
dialect that can do this treats it as a request-side opt-in — a model does not volunteer
citations — and several bill a cited answer differently.

The dialects agree on almost nothing, so `Citation` carries only what a person rendering
an attribution needs, and every field is optional. An absent offset means the provider did
not say where in the answer the citation applies; it does not mean position zero. Use
`span_of()` rather than slicing by hand — it returns `""` for a citation with no offsets,
which is the honest answer, and clamps a provider's off-by-one to a short span rather than
raising mid-render.

Streaming callers get each attribution as it lands, via a `CitationDelta`, without waiting
for the final result.

## Let the Provider Run Its Own Tools

Several providers can search the web or execute code *inside* one request, folding the
result into their own answer. Nothing comes back for you to run:

```python
result = client.generate(
    "What shipped in Python 3.14?",
    target="anthropic:claude-sonnet-4-5",
    server_tools=(ai.ServerToolSpec(kind="web_search", max_uses=3),),
)

for use in result.server_tool_uses:
    print(f"{use.kind} ran {use.uses} time(s)")
```

Off by default and never inferred, because each invocation is billed. `max_uses` bounds
that where the provider can express it — a search tool with no ceiling is an unbounded
line item on a request you thought was fixed-price. Providers that take no ceiling report
it dropped rather than accepting it silently.

Unlike every other unhonored request parameter, a server tool the target cannot run is
**refused before dispatch** rather than reported dropped. The distinction is what you get
back: a dropped `temperature` still answers your question, while an answer produced
without the search you asked for is a different answer built from stale training data —
and it looks exactly like a good one. Two things are checked: whether this library has a
wire form for that provider at all, and whether the model itself supports it.

`ServerToolUse` carries a count and nothing else. What the provider searched for is your
own content and its reasoning about it; the count is what you actually need, because the
question a result must answer here is how many invocations you just paid for. Streaming
callers get a `ServerToolDelta` when one starts and finishes, which is what distinguishes
a pause for a slow search from a stalled connection.

## Run a Batch at Half Price

Providers sell a deferred tier at roughly half the per-token price, answered within a
window rather than immediately. That is the shape of an eval, a backfill, or an offline
enrichment run:

```python
batch = ai.BatchGenerationRequest(
    requests=tuple(
        ai.GenerationRequest(messages=(ai.user(question),), schema=Answer)
        for question in questions
    ),
    custom_ids=tuple(row_ids),
)
handle = client.submit_batch(batch, target="anthropic:claude-sonnet-4-5")
save_somewhere(handle)          # AnyInfer stores nothing
```

Each line is the same `GenerationRequest` a live call takes, translated through the same
wire builder — so a batched request carries the schema, tools, cache marks, and reasoning
effort its live twin would. That is the whole argument for batching *through* this library
rather than around it: the typed request model and cost accounting are more valuable on
your highest-volume traffic, not less.

Anthropic and OpenAI are both bound. Their APIs differ in shape — Anthropic takes the
whole job as JSON, while OpenAI uploads it as a file and returns results as two more, one
for successes and one for rejections — but that difference stays behind the interface: the
same four calls work against either.

The handle is yours to persist. Run retention is a stated non-goal, and a job answered
hours later in another process is exactly where it would be most tempting to break it —
so there is no registry here to look it up in later.

```python
report = client.batch_status(handle)
if report.finished:
    result = client.fetch_batch(handle)
    for line in result.lines:
        ...
```

Polling and fetching are separate calls because their costs are: a provider charges
nothing to ask about a job and real bandwidth to download one, and a caller waiting on a
24-hour window asks many times and fetches once.

Lines come back in **submission** order even though providers return them in completion
order, so you can zip results against your own inputs without sorting. A batch is not
all-or-nothing: `result.succeeded` and `result.failed` split the lines, because providers
run and bill what worked even when one request was malformed.

## Handle Failures

All public failures derive from `AnyInferError` and carry structured fields. Branch on
those fields when behavior matters; show `hint` to the operator:

```python
try:
    result = client.generate("Hello", target="medium")
except ai.AnyInferError as exc:
    logger.error("generation failed during %s: %s", exc.phase, exc)
    if exc.hint:
        logger.info("next step: %s", exc.hint)
```

The [error catalog](../reference/errors.md) lists every exception, when it is raised,
and what the user will see.

!!! tip "Key Takeaways"
    - `AsyncClient` is the native implementation; `Client` is its thread-safe
      synchronous facade over the same surface.
    - Create one client, reuse it, and close it: it owns connection pools and any
      supervised local servers.
    - Catch `AnyInferError`, branch on its structured fields, and surface `hint`.

## See Also

<div class="anyinfer-see-also" markdown>

- [Quickstart](quickstart.md): from `pip install` to a working result.
- [Stream typed events](streaming.md): consuming the event stream.
- [Sessions](../concepts/sessions.md): continuity across conversation turns.
- [Clients and streams](../reference/api/client.md): the full client API.
- [Error catalog](../reference/errors.md): every exception and its fields.

</div>
