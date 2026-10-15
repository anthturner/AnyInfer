# AnyInfer `core-generation` v0: specification draft

**Historical input:** [master plan](ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md), boxes M1.2 to
M1.4. M1.2 promoted the normative contract into the
[shared specification](../../specification/core-generation.md) and
[maintenance contract](../../specification/MAINTENANCE.md). Those documents own the current
contract; this draft preserves the reviewed input and its reference notes, including assumptions
subsequently corrected in the master plan. It is not an alternate execution specification.

**Evidence baseline:** `13b9e65` on `develop`, `jsonschema` 4.26.0, `jsonschema-specifications`
2025.9.1, Python 3.11+.

Decisions A1 to A16 in the master plan are settled and are not restated here.

## 1. Profile, vocabulary, verdicts

The profile is named `core-generation`, revision `v0`. An implementation claims the profile
by passing every mandatory case in the frozen corpus release `core-generation-v0`.

| Term | Meaning |
|---|---|
| Operation | One accepted generation request, buffered or streaming. |
| Route attempt | One attempt against one target. A route has ordered targets; each target has a retry budget. |
| Adapter entry | One call into the adapter with a wire request. Original requests, corrections, retries, and fallbacks each count. Health skips, duplicate-target skips, and preflight rejections do not. |
| Correction | An adapter entry produced by the native repair transition. A caller's original text containing the repair template does not make an entry a correction. |
| Issue | One structured validation or extraction finding (§7). |
| `unsupported_input` | The outcome when a request uses something the profile excludes. Decided before any adapter entry. |
| Extension | A feature the profile excludes but an implementation supports deliberately (A15). |

Case verdicts: `pass`, `fail`, `error` (a harness/setup failure, fatal runtime failure, or
missing required evidence), and `extension`. An extension verdict requires a case explicitly
marked for that exact feature and an implementation declaration. The driver honestly records
the native outcome, including a native rejection or assessment exception on the excluded
input; it neither manufactures `unsupported_input` nor counts extension as `pass`. A missing
portable projection outside the admitted domain is expected, rather than a capture failure.
Harness faults, skipped execution, unavailable required evidence, and genuine cancellation
must not be swallowed to manufacture an extension verdict. In particular, Python's native
null-`$schema` warning exception under an error warning policy is an out-of-domain outcome,
not a new portable warning rule or a failed core case. The eight v0 extension names are
`schema.ref`, `schema.combinators`,
`schema.other_dialects`, `schema.boolean_subschema`, `schema.unknown_keywords_ignored`,
`messages.tool_role`, `targets.alias`, and `messages.non_text_parts`.

## 2. Request normalization

A request is: ordered messages, optional schema, sampling, optional repair, optional timeout,
response byte limit, and a route.

| Element | Rule | Out of v0 |
|---|---|---|
| Message | `role` in `system`, `user`, `assistant`; `content` is an ordered list of text parts. A message's text is the concatenation of its text parts in order. | Role `tool` (extension `messages.tool_role`); any non-text part (extension `messages.non_text_parts`). |
| Empty message list | *Python:* unobserved; fixture `normalization/empty-messages` is `to_be_observed`. | |
| Sampling | Fields: `temperature`, `top_p`, `max_output_tokens`, `stop` (list of strings), `seed`, `presence_penalty`, `frequency_penalty`. Unset fields are omitted from the wire request; the provider default applies. `stop` empty is omitted. | Provider option escape hatches. |
| Sampling validity | Negative `seed`, non-finite `presence_penalty` or `frequency_penalty` is `invalid_request` at construction, before acceptance. *Python:* `Sampling.__post_init__` raises `ValueError`. | |
| Timeout | Per adapter entry, including corrections. Default 120 s when unset. | |
| Response bytes | Per adapter entry. Default 1,048,576. | |
| Repair | `max_attempts` integer, default 1 when a repair object is given; absent repair means budget 0. Negative values behave as 0. *Python:* no constructor validation; `_repair_budget` arithmetic makes negatives inert. | |

## 3. Targets and route

A target string is split at the **first** colon: `ollama:qwen3:8b` is provider `ollama`,
model `qwen3:8b`. Rules:

- The model part has leading and trailing whitespace stripped. An empty target, or a target
  whose model part is empty after stripping, is `invalid_request`.
- The provider part is a lowercase ASCII identifier in v0 fixtures, so provider
  normalization is the identity. *Python:* `normalize_provider_id` plus provider alias
  resolution; not exercised by v0.
- A target without a colon is an alias: extension `targets.alias`.
- A resolved target that already appeared earlier in the route is skipped silently: no
  adapter entry and no attempt record. *Python:* the `visited` set in `_route_events`.
- Targets are resolved lazily, one at a time, as the route reaches them. An invalid second
  target therefore surfaces only after the first target has been tried and failed. Target
  errors carry category `invalid_request` with phase `configure`.

| Route field | Default | Meaning |
|---|---|---|
| `targets` | required | Ordered list. |
| `retry.max_attempts` | 2 | Total attempts per target, counting the first. |
| `retry.backoff_base_s` | 0.5 | |
| `retry.backoff_max_s` | 30.0 | |
| `health_gate` | true | Skip a target that failed within `health_ttl_s`. |
| `health_ttl_s` | 30.0 | |

## 4. Schema admission

Applies to the caller's schema, before any adapter entry. Admission inspects keyword presence
at schema positions only. A property named `$ref`, or any value inside `enum`, `const`,
`default`, or `examples`, is data and is not inspected.

| Keyword | Admitted form | Semantics |
|---|---|---|
| root | Object schema, including `{}`. | Boolean root: extension `schema.boolean_subschema`. |
| `$schema` | Absent, or exactly `https://json-schema.org/draft/2020-12/schema`. | Any other value, including `null`: extension `schema.other_dialects` (A7). |
| `type` | One of `object`, `array`, `string`, `number`, `integer`, `boolean`, `null`. | Array of types: extension `schema.combinators`. Booleans are never numbers. An integral binary64 value is an `integer`. |
| `properties` | Object of name to admitted **object** schema. | Insertion order preserved for enumeration (§7). Validates only present properties. A boolean value under `properties`: extension `schema.boolean_subschema`. |
| `required` | Array of unique strings. | One issue per missing name, in array order. |
| `additionalProperties` | `true`, `false`, or absent. | `false` yields one aggregate issue listing all unexpected names. Schema-valued: extension `schema.combinators`. |
| `items` | One admitted object schema. | Applies to each element. Boolean or array form: extension `schema.boolean_subschema` / `schema.combinators`. |
| `enum` | Array of JSON values, possibly empty. | JSON Schema equality: `1` equals `1.0`; `true` does not equal `1`. An empty `enum` is meta-valid and always fails with an `enum` issue. *Python:* verified with `check_schema`. |
| `const` | One JSON value. | Same equality. |
| `minimum`, `maximum` | Finite numbers. | Inclusive. Apply to numbers only. |
| `minLength`, `maxLength` | Non-negative integers. | Length in Unicode code points, not UTF-16 units. |
| `minItems`, `maxItems` | Non-negative integers. | Arrays only. |
| `title`, `description`, `$comment` | Strings. | Annotations; no instance assertion; preserved for prompt injection. Invalid forms still take the late invalid-schema path. |
| `default` | Any JSON value. | Annotation data, not a nested schema; preserved verbatim. |
| `examples` | Array of JSON values. | Annotation data, not nested schemas; a malformed container takes the late invalid-schema path. |
| `$ref`, `$defs`, `$id`, `$anchor` | | Extension `schema.ref`. |
| `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else`, `prefixItems`, `contains`, `uniqueItems`, `multipleOf`, `exclusiveMinimum`, `exclusiveMaximum`, `minProperties`, `maxProperties`, `pattern`, `patternProperties`, `propertyNames`, `format`, `dependentRequired`, `dependentSchemas`, `unevaluatedProperties`, `unevaluatedItems` | | Extension `schema.combinators`. |
| Any other keyword | | Extension `schema.unknown_keywords_ignored`. This names the Python reference's honest treatment: unknown keywords are ignored. An implementation may reject the boundary input, but its driver must not manufacture rejection. |

A **malformed value of an admitted keyword** (for example `required: 17` or `type: 17`) is
admitted. It is assessed only when a response is validated, and yields exactly one issue with
rule `invalid_schema` at the defective input-schema location (§7). Explicitly listed extension
forms take precedence in profile classification; otherwise a malformed admitted keyword is
not rejected earlier or recursively mistaken for a different schema position. v0 fixtures contain at most
one defect per schema (A5). *Python:* `check_schema` raises on the first meta-schema error,
caught in `validate`.

## 5. Mechanism selection and prompt injection

Given the target's capability flags `grammar`, `json_schema`, `json_mode`, choose the first
present in that order; otherwise `prompt`. The chosen mechanism appears on the wire request
and in the result's `structured_mechanism`. In v0 the fixture adapter declares all three
flags false, so `prompt` is the only mechanism exercised and the only value the v0 corpus
asserts. Selection with other flags is O6.

**Injection (normative, A16).** When the mechanism is `prompt` (or `json_mode`, out of v0),
the wire messages are the caller's messages with one instruction added:

```text
Respond with ONLY a JSON value matching this JSON Schema. No prose. Schema:
{schema}
```

where `{schema}` is the canonical rendering of the caller's original schema (§5.1). If the
caller's messages contain a system message, the instruction is appended to the **last** system
message as a new text part whose text is `"\n\n"` followed by the instruction. Otherwise a
new system message containing only the instruction is **prepended**. Corrections are built
from the caller's messages (§8) and then injected the same way, so every adapter entry under
`prompt` carries the instruction exactly once.

*Python:* `_client/wire.py:_inject_schema_prompt`, `schema/mechanism.py:SCHEMA_PROMPT_TEMPLATE`.

### 5.1 Canonical schema rendering

Equivalent to Python `json.dumps(schema, indent=2, sort_keys=True)` with default options:

- Objects: keys sorted by code-point order of the key string; each member on its own line
  indented by two spaces per depth; `"key": value` with one space after the colon; members
  separated by `,` then newline; `{}` for an empty object.
- Arrays: same layout with `[`/`]`; `[]` when empty.
- Strings: double-quoted; `"` and `\` escaped; U+0008, U+0009, U+000A, U+000C, U+000D as
  `\b`, `\t`, `\n`, `\f`, `\r`; other control characters below U+0020 as `\u00XX`; every
  character at or above U+007F as `\uXXXX`, with characters above U+FFFF written as a UTF-16
  surrogate pair of two `\uXXXX` escapes (hex digits lowercase).
- Integers: decimal. Booleans and null: `true`, `false`, `null`.
- Floats: shortest round-trip decimal representation; integral floats carry `.0`; exponent
  form `1e+16` style when Python `repr` would use it. All v0 fixture schema numbers have
  magnitude below 10^15; fractional schema numbers additionally have at most
  three decimal places. This fixture-domain bound also applies inside annotation/enum/const
  data, which are part of the rendered schema. The wider rendering domain is O7.

## 6. Extraction

Input: the response text of one adapter entry.

1. Strip leading and trailing whitespace. *Python:* `str.strip()` strips Unicode whitespace.
   v0 fixtures use only ASCII whitespace at the edges (O2).
2. If the result is empty: issue `response_empty`.
3. Try to parse the whole text as one JSON value. Any JSON value is accepted as a root,
   including scalars and `null`.
4. Otherwise find the first balanced region with this exact scanner:

   ```text
   start = -1; depth = 0; in_string = false; escaped = false; opener = none
   for each (index, char) in text:
     if start == -1:
       if char is '{' or '[': start = index; opener = char; closer = matching(char); depth = 1
       continue                          # anything before the opener is ignored, quotes included
     if escaped: escaped = false; continue
     if char == '\\': escaped = in_string; continue
     if char == '"': in_string = not in_string; continue
     if in_string: continue
     if char == opener: depth += 1
     else if char == closer: depth -= 1; if depth == 0: return text[start .. index]
   return none
   ```

   Only the opener's own kind is counted: inside a `{...}` region, `[` and `]` do not change
   depth. If no region is returned: issue `no_json_candidate`.
5. Parse the candidate. On failure: issue `malformed_json_candidate`. Do not search onward
   for a later candidate.

Duplicate object keys: the last value wins and the key keeps its first position. Integers are
exact. Non-integers are binary64. Decoded nonfinite numbers, including `NaN`/`Infinity` literals
and overflowing exponent forms, do not appear in the v0 response domain (O1).

## 7. Issue model

An issue is `{rule, instance_path, schema_path, params}`.

- `instance_path`: list of segments, each a string (object key) or integer (array index).
  Empty list is the root. `null` for extraction and `invalid_schema` issues.
- `schema_path`: list of segments locating the assertion in the original schema (for
  example `["properties", "age", "type"]`). For `invalid_schema`, the location of the
  defective input-schema location (for example `["required"]` or `["required",0]`),
  retaining index segments when present. This is not the meta-schema constraint path.
  `null` for extraction issues.

| Rule | `params` | Granularity |
|---|---|---|
| `type` | `expected` (string), `actual` (one of `null`, `boolean`, `integer`, `number`, `string`, `array`, `object`; an integral binary64 is `integer`) | One per failing location. |
| `required` | `property` (string) | One per missing name, in `required` array order. |
| `additionalProperties` | `unexpected` (array of strings, sorted by code point) | One aggregate issue. |
| `enum` | `allowed` (array, original order) | One. |
| `const` | `expected` | One. |
| `minimum`, `maximum` | `limit` (number), `actual` (number) | One. |
| `minLength`, `maxLength` | `limit`, `actual` (code-point count) | One. |
| `minItems`, `maxItems` | `limit`, `actual` | One. |
| `response_empty` | none | One; terminates assessment. |
| `no_json_candidate` | none | One; terminates assessment. |
| `malformed_json_candidate` | none | One; terminates assessment. |
| `invalid_schema` | none | One; terminates assessment. Wording free. |

Parameters are derived from the schema value and the instance, never parsed from a message.

**Enumeration order** (before sorting): walk the original schema's keywords in insertion
order; `properties` in schema order restricted to present keys; `items` in element index
order; `required` in array order. *Python:* `iter_errors` traversal.

**Selection order**: stable sort by (1) deeper `instance_path` first, (2) `instance_path`
lexicographic where strings compare by code point and integers numerically, (3) enumeration
order. Then keep the first five. *Python:* `jsonschema.exceptions.relevance` has two further
components (weak/strong keyword classes, and `_matches_type`); within the admitted subset they
never change the order, because all issues at one instance path come from one schema object
and so share the same values. Mixed string/integer segments at the first differing position
cannot occur, because the instance at a given path is either an object or an array.

An `Issue` is the portable semantic projection, not a replacement for an implementation's
native assessment. A repair-capable implementation retains the actual selected native
messages, native metadata, order, multiplicity, and extraction errors for the one assessment
that produced the correction. It formats feedback from that assessment; it must never
revalidate or infer a supposedly selected native result from a lossy `Issue` list.

**Python reference notes (non-normative).** Python keeps current validator selection,
`check_schema`, message, retry/repair, and error-string behaviour, including schemas using
keywords outside this profile. Its private, per-operation collector records an immutable
actual assessment at the production helper invocation: selected native messages and metadata,
the projected ordered `Issue` values, and the input path of a native `SchemaError` including
array indices (never the metaschema constraint path). It records actual pre-sort enumeration
occurrence ordinal/group and selected occurrence order without replaying `iter_errors`.
Native required errors retain the original required array and instance; the projection derives
each missing name from that original ordered array and present keys while preserving association
with the actual occurrences, never from dotted prose. Each assessment has an `assessment_id`
and the `source_entry_ordinal` of the response assessed. A later correction has its own entry
ordinal and a `repair_assessment_ref` linking its actual builder arguments/output and wire
request to that assessment. Source and correction ordinals are not equal; an assessment
need not produce any correction entry. The owned collector is a
`ContextVar` scope installed inside each producer task and reset during cleanup; it persists
through adapter cleanup because validation follows cleanup. Capture is disabled unless the
private driver enables it, introduces no await, yield, task-cancellation manipulation, SDK
export, or integration burden. It retains at most 128 assessments and 1,048,576 snapshot bytes
per operation. Controlled, non-racing capture/projection/cap fault injection makes evidence
unavailable and is a conformance error; it does not change a native exception, result, or
genuine cancellation. The seam does not promise containment for arbitrary user callbacks,
reentrant observers, malicious faults, or cancellation races. The driver requires complete
evidence where a case needs it. The archived full O1 capture is a fallback only if this bounded
seam cannot pass its isolation and proof gates. Its gates include six missing names capped at
five and interleaved/tied-rule selections; with observation disabled, the original selection
and keyword-evaluation pipeline is unchanged.

Python's current rendering remains byte-identical: `<location>: <message>`, with `.a.b[0]`
location syntax and no leading dot, or `<root>`; invalid schema is `the supplied JSON Schema is
itself invalid: <message>`; extraction strings are `response was empty`, `response was not JSON
and contained no JSON object or array`, and `response contained malformed JSON: <detail>`.
Other implementations render their own selected native messages.

## 8. Structured output and repair

1. The response text is extracted (§6) and validated against the **original** caller schema,
   never the projected wire schema.
2. If there are issues and `repair_attempts < budget`, build a correction from the caller's
   messages: the original messages, then an assistant message with the raw response text, then
   a user message with the exact template:

   ```text
   Your previous response did not match the required JSON schema. Errors:
   {errors}
   Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.
   ```

   where `{errors}` is the newline-joined list of `- <rendered issue>` lines from the actual
   selected native assessment. The correction
   then receives prompt injection (§5) and goes to the **same resolved target** with the same
   sampling. Each correction emits a `repair_attempted` telemetry event with a 1-based
   `attempt_number` local to the route attempt. Only the latest invalid response is included;
   earlier corrections are not accumulated.
3. `budget = min(requested, provider_ceiling)` when the provider declares a ceiling. When
   clamped, a `parameter_dropped` telemetry event is emitted with `parameter` =
   `repair.max_attempts` and reason text
   `<provider id> allows at most <ceiling> schema-repair round trip(s); <requested> requested`.
   The result's `warnings` list is **not** affected. *Python:* `ParameterDropped` event;
   `Generation.warnings` holds adapter diagnostics only.
4. If issues remain and the budget is exhausted, the operation fails with category
   `schema_violation` carrying the issues. This is not a provider error: it triggers neither
   retry nor fallback.
5. A provider error during a correction follows §9 like any other adapter entry. A retry
   restarts the route attempt with the **original** request and a fresh repair budget.
   *Python:* trace T1; repair numbers go 1 then 1.

Fixtures encode the correction user text as literal segments with exactly one
`{"$repair_feedback": true}` segment at the `{errors}` position. The placeholder means the
exact outer template above, with the current entry's ordered actual selected native messages as
bullets. A driver verifies those native bullets and the template against its actual assessment;
the corpus compares the ordered portable `Issue` list. It never requires one implementation's
English validator text from another implementation.

## 9. Routing, retry, backoff, health

For each target in order:

1. If the resolved target was already visited in this operation, skip it silently (§3).
2. If `health_gate` and the target failed within `health_ttl_s`, append attempt record
   `skipped_unhealthy` and continue to the next target. No adapter entry.
3. For `attempt_number` from 1 to `retry.max_attempts`: enter the adapter. On success, the
   operation result is this attempt's result.
4. On a provider error: `retryable = predicate(error)`. The default predicate returns false
   for categories `auth` and `context_length` and otherwise returns the error's `retryable`
   flag. (*Python:* an `auth` error first triggers one credential refresh and re-entry when a
   refreshable credential exists; the fixture adapter has none, so v0 never observes it.) If `retryable` and `attempt_number < max_attempts`: wait
   `clamp(max(backoff_base_s * 2^(attempt_number-1), retry_after_s or 0), 0, backoff_max_s)`
   then retry. Retry-After raises the floor; it is not added. The cap applies after. A
   zero-length wait is not performed and not recorded.
5. If not retrying: record the attempt as `failed`; if the error category is `transport`
   or `provider_unavailable`, mark the target unhealthy; continue to the next target.
6. **Post-content guard.** A flag `content_emitted` is set when any content delta (text,
   reasoning, or tool-call) of the current **route attempt** has been produced, in buffered
   as well as streaming consumption. It is not reset by a correction within the same route
   attempt. If a provider error of category `stream_protocol` occurs while the flag is set,
   the operation fails immediately with that error: no retry, no fallback. The consumer
   still receives `attempt_failed` for the attempt, and the target is **not** marked
   unhealthy. So a `stream_protocol` error during a correction, after an invalid first
   response produced text, is fatal. Any other category, including a retryable `transport`
   error after content, follows step 4.
7. If every target fails or is skipped: category `all_targets_failed` carrying the attempt
   trail.

Health recovery: an entry expires once `now - failed_at >= health_ttl_s`; a later success
on the target clears it immediately. Nothing is suppressed permanently.

Attempt record: `{target, outcome, error?}` with outcome in `ok`, `retried`, `failed`,
`skipped_unhealthy`. (`redirected` exists in Python for context-window and content-policy
redirection, O5.)

## 10. Streaming and public events

Public events in v0: `text_delta {text}`, `usage_update {usage}`, `timing_mark {name in
attempt_start | first_token}`, `attempt_failed {record}`, `stream_ended {result}`.

Semantic ordering rules the corpus asserts:

- `timing_mark attempt_start` is emitted once per **adapter entry** (corrections included)
  and precedes any other event of that entry.
- `timing_mark first_token` is emitted once per adapter entry that produces content, before
  its first content delta.
- An adapter failure during cleanup (`fail_in_cleanup`) occurs after the final event and
  before usage synthesis and validation; the entry is treated as failed with that error.
- When the adapter's final event carries usage and no `usage_update` was seen during the
  attempt, the core emits one `usage_update` with that usage after the last content delta.
  *Python:* synthesized in `_run_attempt`.
- Deltas of an attempt that later fails are visible to the consumer, followed by
  `attempt_failed`, then the next attempt's `attempt_start`.
- A correction starts a new attempt sequence on the same target; the consumer sees the
  invalid response's deltas, then the correction's deltas. The final result text is the
  winning attempt's text alone.
- Exactly one `stream_ended` on success; none on failure.

Fixtures compare **coalesced** event sequences: consecutive `text_delta`s within one attempt
are concatenated before comparison, so chunk boundaries are not asserted.

Buffered generation yields the same result as consuming the stream to the end.

Cancellation and close: cancelling a streaming operation ends it with category `cancelled`
and no `stream_ended`; closing a stream before advancing it yields no result and no error;
closing twice is a no-op. *Python:* zero-advance close observed in the P1 audit.

## 11. Result

| Field | Compared in v0 as |
|---|---|
| `text` | exact string |
| `structured` | JSON Schema equality (§13), or `null` |
| `target` | `{provider_id, model}` exact |
| `finish_reason` | one of `stop`, `length`, `tool_calls`, `content_filter`, `other` |
| `usage` | each of `input_tokens`, `output_tokens`, `total_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` as integer or `null`; `total_tokens` is filled from `input + output` when both are known and the adapter reported no total |
| `timing` | presence only: `first_token_ms` null or non-null; `total_ms` present |
| `structured_mechanism` | one of `grammar`, `json_schema`, `json_mode`, `prompt`, or `null` |
| `repair_attempts` | integer; the winning route attempt's local count |
| `attempts` | list of attempt records |
| `warnings` | list of strings, exact (adapter diagnostics only; empty in every v0 fixture) |

Usage is the winning adapter entry's usage alone; it is not summed across entries. Within that
entry, later non-null usage fields overlay earlier known fields; null never erases a known
field, and fields are never added. The final usage overlays `usage_update` events. At result
assembly only, a missing total is normalized from known input plus output; an adapter-reported
total is retained even when inconsistent.

Out of v0: `tool_calls`, `raw`, `manifest`, `logprobs`, `citations`, `server_tool_uses`,
`cost_usd`, `search_units`, and the partial-object salvage carried by Python's
`SchemaViolationError`.

## 12. Errors

| Category | Retryable default | Phase |
|---|---|---|
| `invalid_request` | no | `null` for request construction errors; `configure` for target and configuration errors |
| `unsupported_input` | no | generate |
| `auth` | no | generate |
| `rate_limit` | yes | generate |
| `transport` | yes | generate or stream |
| `provider_unavailable` | yes | generate |
| `model_not_found` | no | generate |
| `context_length` | no | generate |
| `stream_protocol` | no | stream |
| `schema_violation` | no | validate |
| `all_targets_failed` | no | generate |
| `cancelled` | no | `null` |

Portable error fields: `category`, `retryable`, `retry_after_s` (number or null),
`http_status` (integer or null), `phase` in `configure`, `discover`, `generate`, `stream`,
`validate`, `cleanup`, or `null`. `detail` and `hint` are free text, bounded, redacted; the
corpus does not compare them. HTTP statuses 408, 409, 425, 429 and all 5xx are retryable at
the adapter.

*Python mapping:* `ValueError` from request construction, `ConfigError`, `CredentialError` →
`invalid_request`; `UnsupportedInputError` → `unsupported_input`; `AuthError` → `auth`;
`RateLimitError` → `rate_limit`; `TransportError` → `transport`; `ProviderUnavailableError` →
`provider_unavailable`; `ModelNotFoundError` → `model_not_found`; `ContextLengthError` →
`context_length`; `StreamProtocolError` → `stream_protocol`; `SchemaViolationError` →
`schema_violation`; `AllTargetsFailedError` → `all_targets_failed`; `asyncio.CancelledError`
→ `cancelled` (a raw exception in Python, not an `AnyInferError`).

## 13. Observation value model

All fixture, adapter, expected, and report values are ordinary JSON values. `$special` and
`$codepoints` are ordinary object keys in every position, including schemas, adapter scripts,
and expected results. v0 recognizes no tagged-value interpretation.

- A JSON number without a fraction or exponent has an exact integer lexeme and must be within
  ±2^63. A JSON number with a fraction or exponent is finite binary64; its lexical form,
  including signed zero, is retained where comparison needs it.
- `structured`, `enum`, and `const` use JSON Schema equality (`1 == 1.0`, `true != 1`; object
  key order ignored). Other fields use type-aware JSON equality.
- Nonfinite values and lone surrogates are excluded. An injective tagged codec for those
  values is deferred with O1 and O8.
- `{"$schema_prompt": true}` and `{"$repair_feedback": true}` are placeholders only in the
  schema-typed expected-message segment positions defined in §14. They are never interpreted
  in arbitrary result, schema, request, adapter, or expected JSON.

Numeric decoding invariants are checked before value equivalence: an integer lexeme cannot
be rounded through binary64 merely to compare it. Pure integer observations remain exact
through the v0 bound; mixed integer/float comparisons beyond 2^53 remain O3. All decoded
numbers in the v0 corpus are finite and all decoded strings exclude isolated surrogates.
These bounds and the §5.1 schema-rendering bound qualify the portable claim and fixture
domain. They do not introduce new Python parser checks, earlier schema validation, retry
rules, or a requirement to reject a future response before inference. Explicit extension
boundary cases use §1; other deferred domains carry no v0 equivalence claim.

## 14. Fixture format v0

One JSON file per case. Schema: `specification/schemas/fixture-v0.schema.json`.

```json
{
  "fixture_version": "0",
  "id": "routing/restart-after-correction-transport-failure",
  "family": "routing",
  "profile": "core-generation",
  "description": "Correction fails with a retryable transport error; the route attempt restarts with the original request and a fresh repair budget.",
  "clock": { "start_ms": 0 },
  "request": {
    "messages": [ { "role": "user", "text": "Give me a person." } ],
    "schema": { "type": "object", "properties": { "age": { "type": "integer" } }, "required": ["age"] },
    "sampling": { "temperature": 0 },
    "repair": { "max_attempts": 1 },
    "timeout_s": null,
    "max_response_bytes": 1048576,
    "consume": "stream"
  },
  "route": {
    "targets": ["fixture:alpha"],
    "retry": { "max_attempts": 2, "backoff_base_s": 0.5, "backoff_max_s": 30.0 },
    "health_gate": true,
    "health_ttl_s": 30.0
  },
  "adapter": {
    "max_repair_attempts": null,
    "models": {
      "alpha": { "capabilities": { "grammar": false, "json_schema": false, "json_mode": false } }
    },
    "health_preset": [],
    "script": [
      { "events": [ { "text": "{\"name\": \"x\"}" }, { "final": { "finish_reason": "stop", "usage": { "input_tokens": 11, "output_tokens": 7, "total_tokens": 18 } } } ] },
      { "events": [ { "text": "{\"age\": " } ], "fail": { "category": "transport", "retryable": true, "retry_after_s": null, "http_status": 503, "phase": "stream" } },
      { "events": [ { "text": "{\"name\": \"x\"}" }, { "final": { "finish_reason": "stop", "usage": null } } ] },
      { "events": [ { "text": "{\"age\": 7}" }, { "final": { "finish_reason": "stop", "usage": { "input_tokens": 20, "output_tokens": 5, "total_tokens": 25 } } } ] }
    ]
  },
  "expected": {
    "status": "observed",
    "calls": [
      { "model": "alpha", "role": "original", "mechanism": "prompt",
        "timeout_s": 120, "max_response_bytes": 1048576,
        "messages": [ { "role": "system", "text": [ { "$schema_prompt": true } ] }, { "role": "user", "text": "Give me a person." } ] },
      { "model": "alpha", "role": "correction", "mechanism": "prompt",
        "timeout_s": 120, "max_response_bytes": 1048576,
        "messages": [ { "role": "system", "text": [ { "$schema_prompt": true } ] }, { "role": "user", "text": "Give me a person." }, { "role": "assistant", "text": "{\"name\": \"x\"}" }, { "role": "user", "text": [ "Your previous response did not match the required JSON schema. Errors:\n", { "$repair_feedback": true }, "\nRespond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences." ] } ],
        "issues": [ { "rule": "required", "instance_path": [], "schema_path": ["required"], "params": { "property": "age" } } ] },
      { "model": "alpha", "role": "original", "mechanism": "prompt", "timeout_s": 120, "max_response_bytes": 1048576, "messages": "same_as_call_1" },
      { "model": "alpha", "role": "correction", "mechanism": "prompt", "timeout_s": 120, "max_response_bytes": 1048576, "messages": "same_as_call_2",
        "issues": [ { "rule": "required", "instance_path": [], "schema_path": ["required"], "params": { "property": "age" } } ] }
    ],
    "clock_advances_ms": [500],
    "telemetry": {
      "repair_attempted": [ { "attempt_number": 1 }, { "attempt_number": 1 } ],
      "parameter_dropped": []
    },
    "events": [
      { "timing_mark": "attempt_start" }, { "timing_mark": "first_token" }, { "text": "{\"name\": \"x\"}" }, { "usage_update": { "input_tokens": 11, "output_tokens": 7, "total_tokens": 18 } },
      { "timing_mark": "attempt_start" }, { "timing_mark": "first_token" }, { "text": "{\"age\": " }, { "attempt_failed": { "outcome": "retried", "error": { "category": "transport" } } },
      { "timing_mark": "attempt_start" }, { "timing_mark": "first_token" }, { "text": "{\"name\": \"x\"}" },
      { "timing_mark": "attempt_start" }, { "timing_mark": "first_token" }, { "text": "{\"age\": 7}" }, { "usage_update": { "input_tokens": 20, "output_tokens": 5, "total_tokens": 25 } },
      { "stream_ended": true }
    ],
    "outcome": {
      "result": {
        "text": "{\"age\": 7}",
        "structured": { "age": 7 },
        "target": { "provider_id": "fixture", "model": "alpha" },
        "finish_reason": "stop",
        "usage": { "input_tokens": 20, "output_tokens": 5, "total_tokens": 25 },
        "timing": { "first_token_ms": "non_null", "total_ms": "present" },
        "structured_mechanism": "prompt",
        "repair_attempts": 1,
        "attempts": [ { "target": "fixture:alpha", "outcome": "retried", "error": { "category": "transport" } }, { "target": "fixture:alpha", "outcome": "ok" } ],
        "warnings": []
      }
    },
    "accounting": null
  }
}
```

Rules:

- `request.messages[i].text` is a string, or a list of literal strings. In `request` only
  literal strings are allowed. `expected.calls` message text may additionally contain the
  schema-typed segments `{"$schema_prompt": true}` and `{"$repair_feedback": true}`. The first
  means the exact §5 instruction for `request.schema`; the second is allowed exactly once in a
  correction user's repair-message position and has the §8 meaning. Message text is the
  concatenation of segments. A message with several caller text parts is written as a list of
  strings; comparison is on concatenated text.
- `request.consume` is one of `buffered`, `stream`, `stream_cancel_after_events:<n>`
  (cancel after the n-th public event), `close_without_advance`, `close_twice_after_end`.
- `adapter.max_repair_attempts` is the provider-level repair ceiling (`null` for none); it is
  a property of the fixture provider, not of a model. *Python:* `ProviderDescriptor.max_repair_attempts`.
- `adapter.script` entries are consumed in adapter-entry order across all targets. An entry
  with `fail` and no `events` fails at entry. `fail` after `events` fails mid-stream. An
  optional `fail_in_cleanup` fails after the final event, during adapter cleanup (§10). A
  script that runs out is a driver `error`. Its ordered `events` may contain exactly one-field
  action `{"await_release": "gate-id"}`. This is a driver action, never an adapter event: it
  records entry and signals readiness, then suspends native async execution until the driver
  releases the named gate. In a timeout case the driver never releases it before the native
  timeout outcome. Actions occur at their literal place among events.
- Usage objects anywhere in `expected` may omit fields whose value is `null`; `{}` means all
  six fields null. `timing` values are `"non_null"`, `"null"`, or `"present"`.
- Attempt records and `attempt_failed` carry `error: {category}` when the outcome is
  `retried` or `failed`, and no `error` key otherwise.
- `adapter.health_preset` seeds unhealthy marks: `{"target": "fixture:beta", "failed_at_ms": -1000}`.
- `clock`: the driver injects a virtual monotonic clock for health and backoff only. Every
  non-zero requested backoff advances it by the requested amount and is appended to
  `clock_advances_ms`. It does not trigger native adapter timeouts.
- `expected.calls[i].messages` is the literal list (as delivered to the adapter, after
  injection) or `"same_as_call_<n>"` with 1-based `n`.
- `expected.calls[i].issues` is required for `correction` entries and forbidden otherwise;
  it is the ordered portable projection of the actual assessment. `timeout_s` and
  `max_response_bytes` are required on every entered call and carry effective values (120 and
  1,048,576 when omitted by the request). A shared deterministic reference is permitted only
  where the schema explicitly defines omitted fields as those effective defaults.
- `expected.telemetry.repair_attempted` and `.parameter_dropped` are ordered lists; each
  `parameter_dropped` entry is `{"parameter": "<name>"}`.
- `expected.events` is coalesced (§10). `expected.outcome` is exactly one of `result`,
  `error`, or `none` (for `close_without_advance`); `error` compares `category`, `retryable`,
  `http_status`, `phase`, and for `schema_violation` the `issues` list.
- `expected.status` is `observed` or `to_be_observed`; M1.7 replaces every `to_be_observed`.
- `expected.accounting` is reserved (A4) and must be `null` in v0.
- The driver asserts: the number of adapter entries equals `expected.calls` length; each
  entry's model, role, messages, mechanism, effective timeout, and byte limit match; correction
  `issues`, actual builder arguments/output, repair suffix, and entered wire request refer to
  the same actual `assessment_id`. Its `source_entry_ordinal` identifies the earlier response;
  the correction's `entry_ordinal` is separate. No correction-call reference is invented when
  preparation or adapter entry did not occur. Role comes from the actual repair transition,
  not substring detection in caller messages;
  the wire request's sampling equals `request.sampling` with unset fields absent. Dotted key
  `['a.b']` and nested key `['a','b']` collision cases prove the driver observed typed selected
  paths, not merely rendered strings.
- Extension cases (§17, marked E) have `expected.outcome.error.category` =
  `unsupported_input`, zero `calls`, and a top-level `"extension": "<name>"`. An
  implementation whose report lists that exact name receives verdict `extension` for the case.
  Extension is allowed only for explicitly marked cases. Section 1 distinguishes honest
  out-of-domain native outcomes from harness faults and missing required evidence. A
  projection unavailable because that input is outside v0 is not fabricated or compared.

Transport fixtures exercise a real native OpenAI-compatible adapter over a fake HTTP transport,
not only its parser. `transport-v0` has two mutually exclusive input variants:

- `kind: "adapter"`: `input.adapter_config` configures the adapter and `input.wire` supplies
  the native wire request. `expected.adapter_outcome` contains either the ordered typed
  adapter events or an error. Both buffered HTTP and streamed HTTP normalize to adapter
  events; a buffered HTTP response does not create a second adapter result API.
- `kind: "core_http"`: `input.adapter_config` configures the native adapter and
  `input.operation` contains the profile request and route. The real native core runs over
  that adapter; `expected.core` reuses the core expectation rules, including actual
  assessment linkage, correction history, public events, result, and error.

Both variants supply an ordered `responses` array of `{status, headers, byte_chunks}`;
each byte chunk is `{bytes: "<base64>"}`. It supplies one response per actual HTTP exchange,
including corrections/retries; an exhausted response script is a driver error. The driver
compares every actual request against the ordered `expected.http_requests` array of
`{method, path, headers, json, stream_mode}`. Associated adapter-entry observations compare
effective `timeout_s` and `max_response_bytes` to their expectations. These are wire-request
limits, not invented HTTP header fields or a nonexistent `HttpClient` byte-limit argument.
Functional raw-byte cases prove enforcement. Headers use nonsecret credential placeholders.
The adapter receives only input configuration and scripted responses, never expected requests
or outcomes. Parser-specific cases additionally compare normalized events without coalescing;
byte chunks are fed at the specified boundaries but are not assumed to equal SSE frames.

The HTTP proof covers buffered and streamed modes, message projection, supplied/omitted
sampling, prompt projection, status 503/non-SSE input, raw-byte caps including multibyte
UTF-8, and correction-entry byte-budget reset through the real core. Fixture schemas enforce
the two variants and their distinct expected outcomes before any driver executes them.

Timeout proof has two complementary parts, with the same predicates in every native driver.
An owned test spy observes distinct native timeout-context/timer creation, effective duration,
and disposal for each adapter entry, including correction and cleanup. A separate
`await_release` case actually suspends native async execution until the real timeout fires,
verifies the native transport-error mapping/trail, and uses an independent wide watchdog only
to detect a stuck test. The driver compares lifecycle/readiness order and configured duration,
not exact elapsed milliseconds. It does not advance the health/backoff clock, replace the
production timeout, or inject a scripted `TransportError` as proof. Python observes its real
`asyncio.timeout`; C# observes its native timer/cancellation implementation. A missing native
spy/assertion is unavailable evidence, not a substitute passing case.

## 15. Reference manifest

`specification/reference/python-<rev7>.json`:

```json
{
  "implementation": "anyinfer-python",
  "reference_run_revision": "<40 hex>",
  "source_tree": { "clean": true },
  "driver": { "path": "tests/testing/portable/", "git_revision": "<same committed revision>" },
  "interpreter": "CPython 3.x.y",
  "environment": { "path": "specification/reference/python-<rev7>.environment.json", "sha256": "<sha256>" },
  "packages": { "httpx2": "...", "jsonschema": "...", "jsonschema-specifications": "...", "referencing": "...", "attrs": "...", "rpds-py": "..." },
  "validator": { "selected": "...", "defaults": "...", "resource_identities": ["..."] },
  "warning_policy": "error",
  "produced_at": "<ISO 8601>"
}
```

The reference environment artifact records the complete dependency lock and actual selected
resource identities; it does not change production dependency ranges. Development runs may
write pending placeholders. Before the final reference run, the coordinator commits the exact
source, driver, specification, and fixture inputs. The oracle refuses a missing, mismatched, or
dirty required binding and verifies import provenance against the committed input tree.

`reference_run_revision` is the committed revision A that executed the reference source and
driver. It can precede the later release commit B that adds generated manifest/release assets.
The exact Python baseline preflight applies only to oracle reproduction or `--write-reference`:
reproduction checks out A and may supply frozen assets from B through `--root`. Ordinary later
Python or native conformance runs verify frozen release assets and report their own source and
environment binding; they need not equal A.

**Bootstrap order.** Before a release file exists, development and clean reference runs
produce explicitly unreleased observations against the hashed §17 inventory. These private
driver diagnostics record cases, counts, input identity, and source/environment binding;
they are not `report-v0` and cannot pass a port/release comparison. Development observations
fill pending expectations. After the reconciled inputs are committed at A, the clean reference
observation run produces the reference manifest and environment artifact. M1.G then creates
the candidate release file, verifies its hashes/inventory, and runs the full Python corpus
again to produce the first qualified `report-v0` with a real `release_sha256`. Only a complete
zero-failure/error report and the cold review permit sealing that release. Conformance reports
are not release inputs, so this order has no report/hash dependency cycle. Any additional tool
commits are reported honestly; A remains the original reference-run revision and B denotes the
later commit containing the sealed release assets, not necessarily A's immediate child.

While a C# driver or HTTP adapter is still being built, a selected-family run similarly emits
development observations only. M2.4 proves the available core/driver subset; after M2.5 adds
HTTP support, the complete inventory must execute before either a qualified report or a
profile claim is possible.

### 15.1 Release file

`specification/releases/core-generation-v0.json`, written by `scripts/freeze_release.py`:

```json
{
  "release": "core-generation-v0",
  "profile": "core-generation",
  "profile_revision": "v0",
  "created_at": "<ISO 8601>",
  "reference_manifest": "specification/reference/python-<rev7>.json",
  "files": { "specification/core-generation.md": "<sha256 hex>" },
  "case_inventory": [ { "id": "repair/zero-budget", "path": "specification/fixtures/core-generation/repair/zero-budget.json", "family": "repair", "extension": null } ]
}
```

`files` lists this release's normative `specification/README.md`, `core-generation.md`,
`MAINTENANCE.md`, every schema, the §17 inventory asset, all exact corpus fixture inputs, and
the reference manifest and environment artifact. Paths use forward slashes and code-point
ordering; hashes are SHA-256 of raw bytes. Generated conformance reports and the release file
itself are excluded; the reference manifest and environment artifact are included. A `.gitattributes`
rule `specification/** text eol=lf` keeps those bytes platform-stable. `case_inventory` is the
complete, unique release ID set derived from the inventory asset and names every case's kind,
path (or `null` for a driver assertion), family, and extension name or `null`. The embedded
case set must equal that asset's cases. There are no pending expectations. Reports cite the
SHA-256 of actual release-file bytes; verification rejects missing, changed, or unexpected
release inputs and does not glob later releases' fixtures into this release.

Release retrieval is immutable: an annotated Git tag targets commit B containing the release
manifest and every hashed asset. An external support declaration records that tag and its
resolved commit, avoiding a release-file self-reference. A changed asset creates a new release
ID; prior assets remain retrievable from their tag, and every driver accepts `--root` pointing
to an extracted matching corpus tree.

### 15.2 Maintenance principles

A compatible change adds a new release without changing an old release's assets; a breaking
change increments the profile revision and requires explicit migration and rebaseline review.
Reference rebaselining records a new reference source/environment binding and release ID after
the required change checks. Each implementation declares the releases it supports and verifies
them by immutable retrieval. Publishing, ownership, and support-window decisions precede any
independently supported public releases; none authorizes an implementation here.

## 16. Conformance report

`specification/schemas/report-v0.schema.json`. This is an illustrative one-case shape excerpt;
an actual qualified report must contain the complete released inventory:

```json
{
  "report_version": "0",
  "release": "core-generation-v0",
  "release_sha256": "<hash of the release file>",
  "implementation": { "name": "anyinfer-dotnet", "version": "0.1.0", "source_revision": "<commit>", "driver_revision": "<commit>", "runtime": ".NET 8.0.x", "os": "...", "dependencies": { "<component>": "<exact version>" }, "extensions": [] },
  "cases": [ { "id": "repair/exhaustion-two-invalid", "verdict": "pass", "detail": null } ],
  "counts": { "pass": 1, "fail": 0, "error": 0, "extension": 0 }
}
```

Each driver records its actual implementation/driver revisions, runtime, OS, and dependency
versions. It reports its own environment rather than copying the Python reference binding.
Qualified proof uses identified committed implementation/driver inputs; unreleased or
unidentified development runs do not acquire a release claim by copying a release hash.
Counts are derived from `cases` by the driver, never typed by hand. The Python reference report
lists all eight v0 extension names in `implementation.extensions`. A valid report binds the
trusted release hash and contains each inventory ID exactly once: every core, HTTP, and required
driver-assertion case. It contains no extra or duplicate ID; family and extension eligibility
match the release inventory; mandatory driver evidence is present. Missing evidence is `error`,
never `pass` or `extension`. Comparison fails for either report containing `fail`, `error`, or
incomplete coverage, even if those failures match. Python `extension` and another
implementation's `pass` are comparable only for the same explicitly eligible case.

Drivers and comparison reject an empty report, missing/duplicate/extra IDs, stale counts,
mismatched hashes, changed normative text or reference manifest, and an extension verdict on a
core case.

## 17. Case inventory for v0

IDs are `family/slug`. Counts and extension-case totals are mechanically derived from the
case inventory after authoring; no fixed total is normative here. E marks an explicitly
eligible extension case. M1.4 writes `specification/inventories/core-generation-v0.json`
against `specification/schemas/inventory-v0.schema.json` (M1.3). It contains:

- `profile`, `profile_revision`, and `requirements`: records with unique `id`, normative
  `spec_ref`, and a nonempty `case_ids` list covering that requirement.
- `cases`: unique records with `id`, `kind` (`fixture` or `driver_assertion`), `family`,
  `path`, and `extension` (one declared feature name or `null`). Fixture paths name actual
  release inputs. Driver assertions have `path: null` and a `recipe_ref` to their shared
  normative predicate below; they do not pretend to be portable Python test files.

M1.2 promotes the normative fixture protocol and driver recipes into the shared specification
along with the core behavior. M1.3 owns `scripts/validate_fixtures.py --check-coverage`, which
checks the inventory schema, unique IDs, resolved requirement mappings/recipes, fixture files,
and eligible extension names. A staged `--family core-generation` check permits only the
explicitly excluded transport obligations to remain pending at M1.4. M1.6 and freeze use the
full check; no staged check qualifies a release report. Every named case below must be in the
inventory, every normative v0 requirement must map to a case, and no fixture or mandatory
driver assertion can silently disappear. A skipped/unexecuted driver assertion is an error.

**normalization:** `roles-ordered-text`, `multi-part-text-concatenated`,
`sampling-omitted-when-unset`, `sampling-supplied-fields`, `target-first-colon-model-with-colon`,
`target-model-whitespace-stripped`, `target-empty-model-invalid`, `invalid-sampling-negative-seed`,
`empty-messages` (to_be_observed), `unsupported-tool-role` (E), `unsupported-alias-target` (E),
`unsupported-image-part` (E).

**schema-admission:** `admitted-full-subset-valid-response`, `unknown-keyword-ignored` (E), `unsupported-ref` (E),
`unsupported-anyof` (E), `unsupported-dialect-draft7` (E), `unsupported-dialect-null` (E),
`unsupported-boolean-subschema` (E).

**extraction:** `whole-json-object`, `fenced-object-in-prose`, `prose-then-array`,
`braces-inside-string`, `empty-response`, `malformed-first-candidate-no-rescue`, `scalar-root-42`,
`integer-above-2pow53-preserved`, `duplicate-key-last-value-first-position`.

**validation:** `missing-required-one`, `six-missing-required-first-five-in-order`,
`additional-properties-aggregate`, `type-mismatch-string-for-integer`,
`integral-float-is-integer`, `enum-numeric-equality`, `enum-empty-always-fails`,
`const-fails`, `minimum-fails`, `maximum-fails`, `minlength-counts-code-points`,
`maxlength-fails`, `minitems-fails`, `maxitems-fails`, `nested-deeper-issue-first`,
`ordering-tied-rules`, `dotted-key-nested-path-collision`, `literal-reserved-key-objects`,
`boolean-not-number-or-integer`, `malformed-required-17-invalid-schema`,
`malformed-type-17-invalid-schema`, `malformed-title-17-invalid-schema`,
`malformed-examples-17-invalid-schema`, `malformed-schema-extraction-precedes-assessment`.

**repair:** `valid-no-correction`, `invalid-without-repair-fails`, `invalid-then-valid`,
`exhaustion-two-invalid`, `zero-budget`, `provider-ceiling-clamp-parameter-dropped`,
`negative-budget-behaves-as-zero`, `correction-prompt-exact-template`.

**routing:** `retryable-then-ok-same-target`, `nonretryable-falls-over`,
`auth-never-retried`, `backoff-retry-after-floor`, `backoff-cap`, `health-skip-in-trail`,
`health-recovery-after-ttl`, `duplicate-target-skipped`, `all-targets-failed-trail`,
`restart-after-correction-transport-failure`, `cleanup-failure-after-final-restarts`,
`post-content-stream-protocol-no-retry`, `post-content-stream-protocol-in-correction-fatal`,
`post-content-transport-error-retries`, `lazy-invalid-second-target`.

**streaming:** `buffered-equals-streamed`, `failed-attempt-deltas-visible`,
`first-token-mark-once-per-attempt`, `synthesized-usage-update-from-final`,
`finish-reason-other`, `cancel-mid-stream`, `zero-advance-close`,
`usage-overlay-and-null-preservation`, `reported-total-not-recomputed`.

**lifecycle:** `repeated-close-idempotent`; required driver assertions include
`driver/concurrent-operations-independent`, `driver/assessment-completeness`,
`driver/timeout-effective-default-explicit`, `driver/timeout-reset-per-entry`,
`driver/timeout-cleanup-disposal`, and `driver/http-correction-byte-budget-reset`.

Their shared predicates, implemented and reported by every native driver, are:

| Driver assertion | Required observed predicate |
|---|---|
| `driver/concurrent-operations-independent` | Run two operations concurrently with separate scopes/scripts; each result, assessment and entry trail belongs only to its operation. |
| `driver/assessment-completeness` | Observe actual selected occurrences and native feedback, including extraction, late invalid-schema failure and exhaustion; connect source assessment to any actual correction builder/wire. Dotted and nested paths remain distinguishable. Fault/cap controls preserve native behavior and cause evidence failure rather than a false pass. |
| `driver/timeout-effective-default-explicit` | Capture the effective default and supplied timeout and byte limit at each native adapter entry; an unreleased async gate causes a real native timeout with the documented error mapping/trail. |
| `driver/timeout-reset-per-entry` | Observe a distinct actual native timer/context configured for each original/correction/restarted entry; the prior context is disposed. Verify actual timeout behavior separately from this lifecycle observation. |
| `driver/timeout-cleanup-disposal` | Show cleanup runs within the entry's timeout, exercise a real timeout during suspended cleanup, and verify native timer/resource disposal and terminal outcome. |
| `driver/http-correction-byte-budget-reset` | Drive an invalid HTTP response then a correction through the real core/adapter. Each response stays below its own raw-byte limit while their combined bytes exceed it; success proves budgets reset. Separate overflow cases prove both buffered and streaming enforcement, including multibyte UTF-8. |

Native-specific instrumentation implements these predicates without replacing production
control flow; Python's private capture/timer mechanisms are not a required API for other
languages. Required facts unavailable in any native driver yield `error`, never a copied
Python pass. Exact expected native outcomes still come from the bounded reference run and
the reconciliation gate; these recipes do not claim that run has happened.

**transport/openai-chat:** `single-frame`, `frame-split-mid-json`, `trailing-usage-chunk`,
`done-sentinel`, `protocol-error-after-content`, `non-sse-error-body-status-503`,
`outbound-buffered-message-projection`, `outbound-streamed-sampling-supplied`,
`outbound-sampling-omitted`, `raw-byte-cap-multibyte-utf8`, and
`correction-byte-budget-reset`.

Selection and execution of native structured-output mechanisms remain O6. The v0 fixture
adapter advertises only the prompt mechanism.

## 18. Open items carried to v1

| ID | Item |
|---|---|
| O1 | Nonfinite JSON literals and the future injective tagged codec (Python accepts some forms; STJ differs). |
| O2 | Unicode whitespace at response edges. |
| O3 | Integers beyond ±2^63 in responses and schemas; exact int-versus-float equality above 2^53. |
| O4 | Stable numeric error codes; needed when a second port exists. |
| O5 | `redirected` attempt outcome (context-window and content-policy routes). |
| O6 | Native JSON-mode, grammar, and tool-call structured-output mechanisms, including selection cases. |
| O7 | Float rendering in canonical schema JSON beyond the v0 bound (exponent form, `repr` edge cases). |
| O8 | Lone-surrogate round-trip through `System.Text.Json` escapes and its future tagged-codec representation. |
