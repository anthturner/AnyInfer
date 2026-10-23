# Rich generation v1

This is an input-only cross-runtime profile for rich generation. It supplies literal
requests, descriptors, controlled adapter actions, and offline HTTP response/SSE inputs.
It contains no expected result, event, wire-request, exception, telemetry, or cleanup
output. Observers use the public client APIs and record those facts independently.

Inline bytes are base64 fixture data. Observer evidence derives their length and SHA-256
from actual captured values; it never carries the bytes. URLs, option values, metadata,
public payloads, citations, server-tool sources/output, and normalized final raw values are
synthetic fixture facts and compare exactly. Authentication values are neither inputs nor
observations.

`validation` cases normalize only the equivalent constructor/request validation outcome;
they must also record that no provider dispatch occurred. Timing comparisons use presence
and event order, never elapsed values. Product telemetry and manifest privacy are tested
from actual serialized fields: planted payload markers must be absent from their default
forms while remaining visible through the relevant public return/event surface.

HTTP scripts supply only responses or SSE frames. They never contain an expected request;
the actual request is observer output.

## Machine grammar and observation projection

`schema.json` closes every semantic construction object.  `route`, `schema`, `repair`,
descriptors, requests, scripts, procedures, barriers, citations, sources, usage,
failures, terminal phases/logprobs/server-tool counts, and client setup have named keys
only.  The only intentionally open value domains are recursive JSON values: caller JSON
schema, provider options, and raw payloads.  Those payloads remain JSON data rather than
observer commands.  Validation cases carry their literal invalid part in `messages`; a
procedure selects only a closed public entry point and exact script consumption.

`observations.schema.json` retains the six provenance-envelope fields and records facts
only. `public` contains the selected entry point, ordered discriminated events, and either
the public result or error; terminal results include target, attempts, timing presence and
order, usage, tool calls, nested logprobs, citations, server-tool uses, and exact raw JSON.
`wire.calls` records every actual dispatch. Its closed `adapter` branch represents the
complete WireRequest surface exercised here: model, ordered typed messages/parts, media
byte length/SHA-256, sampling, reasoning wire JSON, structured-output mechanism/schema
name/schema, tools, tool choice, stream, timeout, response limit, cache marks, server
tools, citations, logprobs, extra options, and absent/null/value session-state distinction.
Its separate `http` branch is a captured transport body. Only caller schema, reasoning
wire/options, and the actual HTTP body are recursive JSON; semantic tool arguments and
session/translator data use the named canonical-JSON-plus-digest record.

The adapter projection mirrors the normalized `WireRequest` rather than a provider HTTP
payload: messages have only role and ordered content, content uses the closed text/tool/media
union, and `max_response_bytes` is a positive byte ceiling. Tool choice is a string;
reasoning, schema, and options use canonical JSON evidence; server tools retain ordered
kind/max-uses records. No media bytes or metadata values are captured.

`telemetry` is a required closed bundle of emitted event projections and the manifest
projection. Each telemetry event has typed stable facts and serialization evidence captured
from the actual default serialization before comparison: every serialized field path and
every serialized string leaf's path, UTF-8 length, and SHA-256. The manifest records stable
operation/target/request-shape/metadata-key/payload-null-or-present facts plus the same
serialization evidence. A recorder cannot erase a payload field and claim privacy: an
unexpected serialized field remains in `field_paths`; text remains digest-evidenced rather
than retained. RequestStarted metadata values are intentionally represented exactly, while
the privacy case requires its planted marker to be absent from default manifest values and
answer/reasoning/raw markers to remain absent from default telemetry and manifest forms.

Timing evidence is limited to presence and ordering facts (for example, attempt start
before first content); no elapsed duration is compared. Authentication headers, tokens,
and endpoint credentials are excluded from both input and projection.

The former corpus SHA-256 `ae9ddf5fc2482fe6790af97bd186027f5678f8352524df90203d97fb13da919c`
was an unfrozen draft and is superseded. The canonical UTF-8/LF corpus SHA-256 is
`9cff7a50fbfd553ebcfed25186173579fff582796721d0e83cc656e116cc1777`.

## Observation absence and serialization paths

A request constructor may fail before a client operation or manifest exists. Record an
actually absent manifest as `null`; never synthesize request-shape evidence from attempted
invalid inputs. Present manifests still satisfy the complete closed manifest projection.

Serialization paths use RFC 6901 JSON Pointers. The root is excluded; every object member
and array item contributes its pointer, with `~` escaped as `~0`, `/` as `~1`, and array
indices represented as `/0`, `/1`, and so on. Sort field paths and string-leaf records by
pointer. Record every actual path and string leaf before any comparison normalization.

## Execution corrections before first qualification

The media HTTP case supplies an inline document alongside a URL image and inline audio.
Its four-byte total ceiling covers the one document byte plus three audio bytes; URL
references do not count as inline bytes. The separate document-URL refusal case remains
unchanged. This corrects a literal-input contradiction with the adopted chat contract.
`TargetResolved` retains its own closed telemetry projection with actual request ID and
target; it is not omitted or relabeled as another event. These prequalification changes
introduce no expected SDK output and do not change released foundational assets.

Literal client settings disable the context gate and bundled catalog so this profile
measures rich generation independently of context budgeting and catalog refreshes. Routes
preserve the target order, retry count, and health-gate setting supplied in each literal route;
each scripted invocation therefore corresponds to one consumed script. The fallback input supplies one attempt per target with health gating disabled. These are
explicit input settings, not SDK defaults. An adapter script selects the controlled adapter even
when its descriptor names the OpenAI dialect; HTTP scripts and script-free OpenAI refusal
inputs select the generic Chat Completions adapter through its public transport seam.

Actual `UsageEstimated` events retain field name and method; `RetryScheduled` retains the
attempt number, configured numeric delay, and error. Retry delay is policy data rather than
an elapsed measurement. Every event still carries its actual default serialization evidence.

For an early-close procedure, the public outcome is that of `aclose`/`DisposeAsync`.
A pending reader may need cancellation to quiesce before close completes. Record an
actually observed cancellation as cleanup `reader_cancelled` with id `stream`; do not
replace a successful close outcome with that internal reader outcome. A caller-cancellation
procedure separately retains the actual caller cancellation as its public error.

Declared numeric controls follow the foundational comparison rule: timeout, sampling
controls, retry policy delay and error retry-after compare numerically with booleans
excluded. This does not reinterpret arbitrary raw, HTTP body or canonical JSON data.
Constructor validation preserves native exception names; the comparison permits Python
ValueError against the ArgumentException family only at the constructor-error boundary.

The positive media HTTP input supplies a well-formed Chat Completions SSE response for
its streaming entry point, including content, finish reason and terminal `[DONE]`. The
previous application/json id-only response was contradictory input, not valid positive
streaming evidence. Its failed capture remains retained; this correction changes an
offline provider input and introduces no expected SDK output.

Error comparison follows the foundational portable-error boundary. Runtime exception class
spellings and free diagnostic detail/hints remain in captures. The shared comparison uses
explicit language pairs only at typed error positions: ProviderError/ProviderException,
UnsupportedInputError/UnsupportedInputException, AllTargetsFailedError/AllTargetsFailedException,
and CancelledError/OperationCanceledException (including TaskCanceledException). Other
classes remain exact. Provider, phase, retryability, retry-after and HTTP status remain
strict; constructor aliases remain limited to validation cases. Free detail/hints are
bounded diagnostic evidence rather than portable wording. Literal scripted failure detail
must still join to the reported attempt/fallback and actual serialization; arbitrary raw
or HTTP objects never gain error-class or diagnostic equivalence from matching key names.

Modern schema validators may describe the same rejection with different diagnostic text.
Repair comparison preserves the original messages and diagnostics, then qualifies the
narrow wording boundary from actual evidence: ordered RepairAttempted errors must match
their telemetry and manifest string-leaf hashes; adjacent adapter calls must use the same
target and preserve prior history; the appended assistant text must equal the rejected
stream entry's TextDelta concatenation. The correction user message must retain the shared
instruction template with exactly those actual error bullets. Only after all these joins
does the comparison copy replace the diagnostic bullets with indexed placeholders. Error
count, feedback template, rejected text, message order and every other wire field remain
strict. This rule does not apply to raw/HTTP payloads, arbitrary similar strings or a
buffered correction without the required stream evidence.

Wire session state retains its actual absent/null/value distinction. A nullable protocol
data member alone does not establish client session or continuation lifecycle support.
