# AnyInfer — draft schema admission and response domain

> **Archived 2026-10-15.** Superseded by the revised [master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md)
> and [specification draft](../SPECIFICATION_DRAFT.md). Kept as input for milestone 3
> (operation accounting) and as rationale. Not an active plan; its checklists and gates do not apply.
> Its §2 admission table was carried into the specification draft §4 with W1 closed (decision A7).

**Status:** planning proposal for selected S1; no frozen dialect/profile or implementation.
**Created:** 2026-10-14. **Evidence HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Resume/status:** [foundation plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Selected-policy owner:** the foundation plan.
**Related:** [repair comparison](ANYINFER_REPAIR_FEEDBACK_DRAFT.md),
[lifecycle matrix](ANYINFER_ACCOUNTING_LIFECYCLE_DRAFT.md),
[P1 evidence](ANYINFER_P1_EVIDENCE_AUDIT.md).

This table proposes the smallest useful schema domain for native generation with
repair. It applies to the caller's original structured-output schema, not schemas
describing kit records. Inclusion is a draft recommendation, not evidence of
cross-language validator parity. No schema, fixture, or runtime file is created.
Selected N1/U1/I1 directions settle representation and coverage direction without
freezing wire tags, numeric limits, or malformed-domain shapes.
The [I1 domain/reporting proposal](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md) now
defines a closed candidate root-shape predicate. Membership limits exact comparison;
it is not a new schema-admission or early-validity check.

**Language path:** Python is the current baseline; Python and C# are the next proof
targets. Any admitted future native language, including Java or JavaScript/TypeScript
on Node.js, must explicitly map N1 numeric and U1 Unicode behavior and parser limits.
The portable contract is versioned data, semantics, and shared corpus expectations,
not Python dataclasses/exceptions or C# types. Each future driver reports its own
environment/source and matches the upstream bundle; no installed Python/.NET or host
environment equality is required. SDKs may be idiomatic; no encoding, validator library,
runtime wrapper, code generator, or native binary is selected.

## 1. Admission is separate from validity and provider projection

The portable input is an ordered JSON object representing a schema, with optional
schema-name metadata outside it. Python's `SchemaSpec`, mappings, and
`model_json_schema()` objects are SDK conveniences; the shared data need not encode
those Python forms. Python chooses a nonempty string `title` as a mapping's schema
name, otherwise `response`; explicit `SchemaSpec.name` is separate metadata.

| Class | Proposed first-profile treatment | Python compatibility boundary |
|---|---|---|
| No schema supplied | No structured extraction/validation or repair. | Preserve current ordinary text generation. |
| Supported features, valid schema | Admit; validate responses against the original schema after provider cleanup. | Provider projection never becomes the validation schema. |
| Supported features, malformed schema | Admit to the native late assessment path; do not convert a caught schema error or an uncaught assessment fault into preflight rejection. | `validator_for()` runs before the `SchemaError` handler. A caught `check_schema()` error returns one invalid-schema feedback string; selection/runtime faults instead escape and do not become ordinary repair feedback. Extraction can fail first and hide that assessment on a particular call. |
| Explicitly excluded feature | A request to a port's bounded first-profile surface reports unsupported before inference. | Python's broader API remains unchanged; this is a declared profile boundary, not a Python rejection policy. |
| Value outside the portable input representation | Report unsupported input representation before inference. | Python host objects/non-JSON schema values are outside the shared claim. Do not silently stringify them. |
| Public construction/coercion failure before acceptance | No accounting operation. | Preserve Python construction timing; it does not become delayed schema validation. |

Admission examines feature presence only at schema locations. A property named
`$ref`, or an object inside `enum`, `const`, `default`, or `examples`, is data and
must not be scanned as another schema. For a malformed value of a recognized
keyword, record that validity is deferred; do not invoke full schema validation as
an admission shortcut. When an excluded feature is explicitly present as well,
unsupported-feature classification takes precedence for the bounded profile.
The classifier needs its own observation cases before freeze.
Late validity handling applies only when native execution reaches assessment:
provider rejection, wire construction, extraction, or cleanup may fail first. Admission
does not promise that a hosted provider accepts every schema in the shared domain.

Malformed root `$schema` is an important distinction: in the installed dependency,
an array or object value can cause `TypeError`, and an integer value can cause
`AttributeError`, during `validator_for()` before the caught meta-validation branch.
These are late assessment faults, not ordinary `invalid_schema` feedback. The bounded
review probe found null metadata produced one caught invalid-schema feedback
string in that helper environment. Subsequent static reading found a warning before
that branch which can become fatal under pytest's warnings-as-errors policy. The
[I1 draft](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md) keeps null metadata outside
exact coverage and owns its predeclared environment/branch controls. Do not suppress
warnings or infer a uniform null-metadata branch from the helper result.
The subsequent [I1 helper audit](ANYINFER_I1_EVIDENCE_AUDIT.md) directly confirmed
the nonfatal feedback and fatal-warning branches, and captured all six R/T variants'
selected error objects. These are helper observations, not generation conformance.
The [native history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md) subsequently confirms
buffered representative late handling and null-policy histories; full native
all-variant input/order binding and profile conformance remain gates.
The foundation plan leaves null metadata's portable reference condition open under W1.
This blocks the affected
freeze decision without changing S1 admission or either Python warning-policy branch.
Other malformed metadata need classified evidence as well; do not guess that all
recognized malformed keywords produce one repairable issue. An invalid ordinary
assertion such as `required: 17` follows whichever native assessment branch it actually
reaches. The lifecycle matrix records completed invocation plus uncompleted assessment
and native operation failure for an escaping fault.

## 2. Candidate admission table

The proposed dialect is Draft 2020-12. Python currently selects the installed
validator through `validator_for`; P1 observed 2020-12 with `jsonschema` 4.26.0.
Pinning this profile's dialect does not change Python's broader dialect selection.
Shapes below describe well-formed feature support, not permission to reject every
malformed value early.

| Feature | Proposed admission | Required behavior / boundary |
|---|---|---|
| Schema nodes | Object schemas, including `{}`, at root, `properties` entries, and `items`. | Empty object schema imposes no assertions. Root and nested boolean schemas are excluded, except the dedicated `additionalProperties` boolean below. Python's public coercion is mapping-oriented. |
| `$schema` | Absent, or root value exactly `https://json-schema.org/draft/2020-12/schema`. | Absent means this profile's pinned dialect. Other dialects, URI variants, and nested dialect switches are excluded; do not rely on unknown-dialect warning/fallback. |
| `type` | One of `object`, `array`, `string`, `number`, `integer`, `boolean`, `null`; may be absent. | Valid arrays of types are excluded initially. A malformed recognized value such as `type: 17` follows late validity handling. Do not coerce response strings/numbers/booleans. |
| `properties` | Object mapping exact property names to admitted object schemas. | Validate only properties present in the response. Names and insertion order are retained; a property declaration alone does not make it required. |
| `required` | Array of unique strings. | Missing properties each produce one issue, following declared array order before relevance sorting. A malformed array remains a late validity case. |
| `additionalProperties` | Boolean `true` or `false`, or absent. | Absent/true permits extras. False produces one aggregate issue for all extras, not one issue per extra. Schema-valued forms are excluded initially. |
| `items` | One admitted object schema, or absent. | Applies to each array item. Boolean items, tuple/prefix schemas, and legacy arrays of schemas are excluded. |
| `enum` | Nonempty array of portable JSON values. | Preserve JSON Schema equality: booleans differ from numbers; numeric equality can match `1` and `1.0`; nested values need the same distinction. Do not replace it with host-language generic equality. |
| `const` | One portable JSON value, including null or a container. | Same equality rules as `enum`. Schema-literal numbers are finite; response-side special numbers are addressed separately below. |
| `minimum`, `maximum` | Finite numeric bounds. | Apply only to number instances and include equality at the bound. No invented type assertion. Python comparison behavior for parsed nonfinite responses must be pinned, rather than replaced with automatic rejection. |
| `minLength`, `maxLength` | Nonnegative integer bounds. | Apply only to strings. Reproduce Python character-count behavior; UTF-16 code-unit length in C# is insufficient for astral characters. Surrogate handling remains a gate. |
| `minItems`, `maxItems` | Nonnegative integer bounds. | Apply only to arrays. Do not reinterpret absence as zero or impose a type assertion. |
| `title`, `description`, `$comment` | String annotations. | No validation assertion, but retain the original values/order for names, provider projection, and schema-prompt injection. They are not generally wire-inert. |
| `default` | Portable JSON value. | Annotation only; never populate missing response fields or repair them locally. Retain it in original-schema/projection evidence. |
| `examples` | Array of portable JSON values. | Annotation only; do not validate examples as responses or traverse them as schemas. Retain original data. |
| Other keywords | Excluded unless explicitly added to this table. | Unknown keywords/annotations are unsupported in this bounded profile, even where Python would ignore them. No silent dropping during admission. |

Explicit exclusions include `$ref`, `$dynamicRef`, `$id`, `$anchor`, `$dynamicAnchor`,
`$defs`/`definitions`, `$vocabulary`, `allOf`/`anyOf`/`oneOf`/`not`, `if`/`then`/`else`,
`pattern`/`patternProperties`, `format`, content encodings/media schemas,
`propertyNames`, dependency keywords, unevaluated keywords, `prefixItems`, `contains`,
`uniqueItems`, `multipleOf`, exclusive numeric bounds, and property-count bounds.
No remote resolution, network access, custom validator keyword, or format-checker
configuration belongs to this initial domain. Exclusion does not remove Python support.

The allowed combinations are recursive; adding an admitted keyword does not restrict
it to a matching `type`. For example, `required` on a string instance has no effect
unless another assertion fails. Contradictory bounds may form an unsatisfiable but
meta-schema-valid schema; do not invent a preflight satisfiability check.

Original schema order is evidence for validator enumeration/feedback selection.
The separate schema-prompt serializer currently sorts keys (`sort_keys=True`).
Preserving the original schema for validation does not assert original-order prompt
rendering; do not reorder the validation input merely to match that renderer.

## 3. Response domain and extraction compatibility

Schema admission does not make every provider response strict finite JSON. S1 retains
the audited Python extraction behavior even for an admitted request.

| Input/behavior | Proposed requirement | Evidence / further precision |
|---|---|---|
| Whole text | Apply Python-compatible surrounding whitespace removal, then try decoding the entire string as a JSON value. | `extract_json`; Unicode whitespace list still needs explicit expectations. |
| Scalar roots | Accept a successfully decoded scalar, including `42`, `null`, or a string. | P1/P4 observes 42; root null is a valid value, distinct from extraction failure's separate error flag. |
| Object/array fallback | If whole-text decoding fails, scan and decode the first region returned by the existing scanner. | Do not replace the scanner with a full mixed-bracket parser. It counts repeats of the initial opening delimiter and its matching closer, with string/escape state. |
| First malformed region | Report failure for that candidate; do not search onward for another valid object/array. | Distinguish no candidate, malformed candidate, and empty response. |
| Duplicate object keys | Last decoded value wins. | P1/P4; first insertion-position behavior and any effect on feedback enumeration also need expectations. |
| Response numbers | Preserve arbitrary Python integer values and Python binary64 floating decoding, including overflow/underflow and signed zero. | Arbitrary integer limits imposed by the interpreter/parser must be measured/pinned. Do not substitute exact decimal arithmetic for floating comparisons. |
| `NaN`, `Infinity`, `-Infinity`, overflowing exponent | Preserve the parser/validator outcome; do not trigger repair solely because strict JSON would reject the spelling/value. | P1 observed NaN and `1e999` -> infinity. Other spellings, schema assertions, and equality outcomes need direct evidence. |
| Boolean/integer distinction | Booleans are not numbers/integers. Integral binary64 floats qualify as integers in the installed Draft 2020-12 checker. | Installed `_types.draft202012_type_checker` inherits the Draft 6 integer override; reading only base `is_integer` is insufficient. |
| Unicode strings/keys | Selected U1: retain exact decoded sequences, including isolated surrogate values, without normalization. | Astral characters, combining marks, escape/pair rules, ordering, trimming/version effects, and actual transport/decoder behavior require evidence before freeze. Native rejection where Python decodes is a compatibility gap, not a preserved-value pass. |
| Missing/native structured response | Initial compatible-chat/scripted profile uses the text path. | Python can recover named forced-tool arguments through `_structured_candidate`; that provider mechanism is outside this first adapter scope. Do not count its exclusion as failed extraction. |

The portable expectation representation must distinguish integer values from binary64
values and support NaN/infinities without putting invalid JSON numbers in kit files.
**Selected N1 direction:** tagged semantic observations: integer with exact decimal
value; finite binary64 with exact representation including signed zero; signed
infinities and NaN category; plus null/boolean/string/array/object values. N1's corpus
observation identity is distinct from schema equality: `enum`/`const` retains numeric
equality of `1` and `1.0` and equal signed zeros, while booleans remain distinct.
Do not apply bit/tag identity to schema assertions. NaN payload/sign are not required
for observation comparison unless an admitted operation proves observable relevance.

**Selected U1 direction:** exact string observations must survive the kit, including
isolated surrogate values accepted by the reference decoding path. An integer
code-point sequence is the candidate escape-independent representation where needed.
A decoded surrogate pair and an isolated surrogate are different observations. Native
public string/result types are not selected by this kit representation.

These are planning types, not frozen wire tags. Nesting, ranges, size limits, special-
value equality details, code-point encoding, and conversion rules require D4 work.
Accounting counts and money remain governed by their separate strict numeric domain;
response parsing permissiveness must not leak into those fields.

## 4. Evidence and draft review gate

Current source anchors are `types/requests.py:SchemaSpec.coerce`,
`schema/validate.py:extract_json/_first_balanced/validate`, `_client/wire.py:build_wire_request`,
and `_client/generation.py:_structured_candidate/_validate/_run_attempt`.
Installed dependency evidence is `jsonschema` 4.26.0's `_types.py`, `_keywords.py`,
`_utils.py`, `exceptions.py`, and `validators.py`; that environment is evidence, not
a permanent requirement to use the same validator package in another language.

| Before this can be normative | Needed evidence / decision |
|---|---|
| Exact admitted domain | Review every row and exclusions, malformed-known-feature versus unsupported-feature precedence, and correct traversal locations. |
| Dialect/version | Pin absent versus explicit `$schema` expectations, validator/specification-resource identities, defaults, and warning policy; recheck dependency/default changes. A driver must not inject a dialect keyword silently to make Python match a pinned profile; a future mismatch needs an explicit disposition. |
| Malformed assessment branches | Distinguish `validator_for` faults, caught `check_schema` failures, and other validator/decoder faults. Include root `$schema` array/object/integer/null, malformed ordinary assertions, extraction failure first, and excluded-feature precedence. No automatic repair/retry on an uncaught assessment fault. |
| Response numeric/Unicode rules | Measure parser limits and boundary outcomes, define tagged expectation equality/encoding, and document native-library gaps. |
| Feedback implications | Review I1's closed root-shape proposal; its helper identities are now captured in the I1 audit. Portable mapping and actual feedback binding through the native core remain gates for every declared variant. Outside the approved exact domain, detailed invalid-schema feedback is qualified/not-covered; branch/history/budget behavior is separately classified. Ordinary instance F1 remains mandatory. |
| Provider projection | Pin supported mechanisms and the compatible adapter's original-to-wire schema transformation; preserve original validation. |
| Schema ownership | Define which actual schema value/order is observed at each assessment. Python's frozen `SchemaSpec` does not deep-freeze nested mappings; do not assume caller mutation is impossible or add a deep-copy policy incidentally. |
| Native-port feasibility | Identify a validator/parser strategy that can represent these responses and match outcomes in each candidate runtime, starting with C#, or explicitly revise the claim before implementation. |

Logical examples for later expectations include missing `age`, an extra object key,
six missing required names, nested keys containing dots/brackets, a string containing
an astral character, `1.0` against integer type, `NaN` with a numeric bound, and an
admitted malformed `required` value after a provider response. These are sketches,
not executable fixtures or new probe results.
