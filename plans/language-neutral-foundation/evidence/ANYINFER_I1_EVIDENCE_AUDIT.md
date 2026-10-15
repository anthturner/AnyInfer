> **Historical supporting record.** Current decisions, language roadmap, readiness,
> and execution order belong to the [active master plan](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
> Old alternatives, next-step directions, and authorization notes below are not current instructions.

# AnyInfer — I1 selected-error and warning-policy evidence audit

**Status:** bounded helper evidence; not a frozen contract or conformance pass.
**Observed:** 2026-10-14. **HEAD:** `13b9e65acfb01038464069ca5fa80f50a9df035c`.
**Authorization:** evidence and planning records under `plans/` only; no implementation,
fixture, saved probe, dependency change, provider request, or git mutation.
**Resume/status:** [foundation checklist](../ANYINFER_LANGUAGE_NEUTRAL_FOUNDATION.md).
**Contract owner:** [I1 domain/reporting draft](ANYINFER_I1_DOMAIN_AND_REPORTING_DRAFT.md).
**Related:** [feedback record](ANYINFER_REPAIR_FEEDBACK_DRAFT.md),
[schema admission](ANYINFER_SCHEMA_ADMISSION_DRAFT.md),
[earlier evidence](ANYINFER_P1_EVIDENCE_AUDIT.md).
The later [native history audit](ANYINFER_I1_NATIVE_HISTORY_AUDIT.md) records buffered-
core histories separately. This file retains its original helper-only evidence scope.

This audit owns the new observations, not the domain or reporting rules. The R/T
primary identities proposed in the draft were observed for all six dialect/order
shapes under both declared policies. Null metadata's warning-dependent branch was
also observed. Neither result expands I1 membership or verifies a generation history.

## 1. Environment and observation method

| Binding | Observed / applied |
|---|---|
| Interpreter | Repository `.venv/Scripts/python.exe`, Python 3.13.15, invoked with `-B`. |
| Source | `D:/projects/AnyInfer/src/anyinfer/schema/validate.py`; unmodified `validate(value, schema)`, with value `{}` in every helper call. |
| Dependencies | `jsonschema` 4.26.0; `jsonschema-specifications` 2025.9.1. |
| Selector default | `jsonschema.validators._LATEST_VERSION` is `Draft202012Validator`. Absent and exact canonical Draft 2020-12 metadata select it in this environment. |
| Meta-validation defaults | No validator, registry, type checker, or format checker was replaced. Installed `check_schema` selects its meta-validator and uses that validator's `FORMAT_CHECKER` when the argument is omitted. |
| R/T policy pair | Temporary `warnings.catch_warnings(record=True)` with `simplefilter("default")`, then separately `simplefilter("error")`, applying to all categories. These are explicit audit policies, not a claim that shell defaults equal pytest. |
| Boundary policy pair | Temporary warning context with `simplefilter("always", DeprecationWarning)`, then separately `simplefilter("error", DeprecationWarning)`. The former records rather than suppresses each warning; the latter promotes it to an exception. |
| Scope of observation | Ephemeral stdin scripts; no file-based test/probe/corpus. No network or inference. The prior P1 302-test result is unchanged. |

For the identity matrix, a temporary `sys.settrace` observer retained the actual
`SchemaError` exception event in the real `validate` frame. It neither replaced
`check_schema` nor ran a second validator to infer what had been caught. Every
matrix invocation produced exactly one such event. The actual object's fields and
context were then inspected; the trace was restored in `finally`.

The discovery observer checked the captured `.message` against the returned feedback
string. Independent checks on both canonical-dialect-first R/T shapes asserted the
stronger complete tuple equality:
`returned == ("the supplied JSON Schema is itself invalid: " + caught.message,)`.
Those checks also asserted one caught object, no warnings, integer-kind instance 17,
the expected input path, context-parent links, and restoration of the prior trace.
Source confirms this exact return expression for all variants.

This is actual caught-object evidence bound to the helper return. It is not an
implemented private feedback bridge, evidence of a constructed/sent repair request,
or proof that tracing has no timing effects. No timing or concurrency claim is made.
The public helper still returns only strings.

### Selected resource byte identities

Paths below are relative to installed `jsonschema_specifications/schemas/draft202012/`.
SHA-256 values were obtained from raw on-disk bytes and independently rechecked.

| Resource | SHA-256 |
|---|---|
| `metaschema.json` | `41DA76F5AFB7CE062D248F762463A92F7CA47E4E0F905B224BA6AFEEF91DED0F` |
| `vocabularies/core` | `C2D12A8E4DD11D336DFC83A3F663AA4C69F0B49B3BEB094FFEB25B5316F4803D` |
| `vocabularies/validation` | `7010A31E541F32D2BE721E2DE348DF75C9B36876A3ED304877FC0ABDA1D37A58` |

The installed specification registry reported 20 resources. These three hashes bind
the inspected meta-schema and the vocabulary files relevant to the selected defects;
they are not a complete registry/dependency/format-checker manifest. The meta-schema
also references other vocabularies. Approval/versioning of an immutable portable
reference environment remains open; a package version or these hashes alone do not
close it.

## 2. Exact-domain matrix: six shapes, twelve helper observations

`D` is the exact decoded string `https://json-schema.org/draft/2020-12/schema`.
Every `17` below is an integer-kind value. Key lists describe actual insertion order.
IDs below are audit-local labels, not published conformance IDs.

| Shape | Root keys in order | Values | Explicit default policy | Explicit error policy |
|---|---|---|---|---|
| R0 | `required` | `required=17` | R identity; one feedback string; no warning | Same |
| R1 | `required`, `$schema` | `required=17`, `$schema=D` | R identity; one feedback string; no warning | Same |
| R2 | `$schema`, `required` | `$schema=D`, `required=17` | R identity; one feedback string; no warning | Same |
| T0 | `type` | `type=17` | T identity; one feedback string; no warning | Same |
| T1 | `type`, `$schema` | `type=17`, `$schema=D` | T identity; one feedback string; no warning | Same |
| T2 | `$schema`, `type` | `$schema=D`, `type=17` | T identity; one feedback string; no warning | Same |

All three R variants shared the R identity below; all three T variants shared the T
identity, including context ordering, under both policies. That supports these exact
shapes in this environment. It establishes no closure under changing a value, adding
a sibling, nesting a defect, combining defects, or changing dependencies/defaults.

### R — actual caught primary error

| Field | Observed value |
|---|---|
| Class | `jsonschema.exceptions.SchemaError` |
| `validator`, `validator_value` | `type`, `array` |
| `instance` | Integer-kind 17 |
| `path`, `absolute_path` | Both `["required"]` |
| `schema_path`, `absolute_schema_path` | Both `["allOf", 3, "properties", "required", "type"]` |
| `schema` | `{"type":"array","items":{"type":"string"},"uniqueItems":true,"default":[]}` |
| `context`, `parent` | Empty context; parent is null. |
| `.message` | `17 is not of type 'array'` |

Actual one-element feedback tuple contains:

```text
the supplied JSON Schema is itself invalid: 17 is not of type 'array'
```

This is a meta-schema array-type requirement on the input's `required` value. It is
not an ordinary missing-required-property issue at a response object.

### T — actual caught primary error and ordered context

| Field | Observed value |
|---|---|
| Class | `jsonschema.exceptions.SchemaError` |
| `validator` | `anyOf` |
| `instance` | Integer-kind 17 |
| `path`, `absolute_path` | Both `["type"]` |
| `schema_path`, `absolute_schema_path` | Both `["allOf", 3, "properties", "type", "anyOf"]` |
| `parent` | Null. |
| `.message` | `17 is not valid under any of the given schemas` |

Actual `validator_value` is this ordered array; actual `schema` is an object whose
only member is `anyOf` with that array:

```json
[
  {"$ref": "#/$defs/simpleTypes"},
  {
    "type": "array",
    "items": {"$ref": "#/$defs/simpleTypes"},
    "minItems": 1,
    "uniqueItems": true
  }
]
```

Actual context has two children in this order. Each is a `ValidationError`, its
`parent` is the actual caught wrapper, its `instance` is integer-kind 17, its relative
`path` is empty, its `absolute_path` is `["type"]`, and its own context is empty.
Their native class does not turn them into response-instance feedback.

| Child | `validator` / `validator_value` | Relative / absolute `schema_path` | Resolved child `schema` / `.message` |
|---|---|---|---|
| 0 | `enum` / `["array","boolean","integer","null","number","object","string"]` | `[0,"enum"]` / `["allOf",3,"properties","type","anyOf",0,"enum"]` | `{"enum":["array","boolean","integer","null","number","object","string"]}`; `17 is not one of ['array', 'boolean', 'integer', 'null', 'number', 'object', 'string']` |
| 1 | `type` / `array` | `[1,"type"]` / `["allOf",3,"properties","type","anyOf",1,"type"]` | The second array alternative above; `17 is not of type 'array'` |

Actual one-element feedback tuple contains:

```text
the supplied JSON Schema is itself invalid: 17 is not valid under any of the given schemas
```

The selected issue is the aggregate wrapper. Selecting its array-type child instead
would erase the first alternative and change the selected defect. The two children
are not two additional selected feedback bullets or cap slots. Native meta-schema
indices remain private evidence, not automatically portable rule identifiers.
S1's exclusion of caller-supplied `anyOf` does not exclude this internal meta-schema
constraint for an admitted malformed `type` value. Matching it does not expand the
caller's admitted schema features or select a general C# combinator implementation.
In the proposed semantic record, the input-schema location is `["type"]` and the
response-instance path is null; the longer meta-schema path is separate evidence.

## 3. Warning-policy and selector boundary matrix

These six schemas were each observed under the boundary policy pair: twelve helper
calls. This is separate from the R/T matrix and its all-category policy pair.

| Entire schema | Nonfatal `always` for DeprecationWarning | `error` for DeprecationWarning |
|---|---|---|
| `{"$schema":null}` | One recorded warning, then one caught invalid-schema feedback string. | `builtins.DeprecationWarning` escapes; no returned feedback tuple. |
| `{"$schema":[]}` | `TypeError: unhashable type: 'list'`; no warning. | Same. |
| `{"$schema":{}}` | `TypeError: unhashable type: 'dict'`; no warning. | Same. |
| `{"$schema":1}` | `AttributeError: 'int' object has no attribute 'decode'`; no warning. | Same. |
| `{"$schema":D}` | Valid selector; helper returns empty tuple; no warning. | Same. |
| `{}` | Default selector; helper returns empty tuple; no warning. | Same. |

`D` in the table denotes its string value, not a literal JSON token. The integer
control here is exactly 1; the earlier audit's separate observation used 17. Neither
observation proves the outcome for every possible integer or malformed metadata.
All these malformed-metadata controls remain outside exact I1 feedback membership.

The null warning is `DeprecationWarning`, reported at `schema/validate.py:109` by
installed `validator_for` using `stacklevel=2`. Exact observed message:

```text
The metaschema specified by $schema was not found. Using the latest draft to validate, but this will raise an error in the future.
```

The nonfatal call returns:

```text
the supplied JSON Schema is itself invalid: None is not of type 'string'
```

Independent traced null checks confirmed one `check_schema` entry and one caught
`SchemaError` under `always`, but zero `check_schema` entries and no `SchemaError`
under `error`. The latter is a selector-warning exception, not a caught invalid-schema
feedback issue. The always-policy caught object has `validator=type`,
`validator_value=string`, null instance, input `path` and `absolute_path` both
`["$schema"]`, meta `schema_path` and `absolute_schema_path` both
`["allOf",0,"properties","$schema","type"]`, and
`schema={"type":"string","format":"uri"}`. It has empty context and null parent.
Its returned tuple was asserted equal to the exact prefix plus its `.message`.
Capturing these fields does not upgrade this outside-domain control to exact I1.

A fresh ordinary Python subprocess using its unchanged default warning filters
returned the null feedback while hiding the deprecation warning. That subprocess
is not pytest. Repository `pyproject.toml` has pytest `filterwarnings=["error", ...]`;
its sole exemption matches an unrelated Starlette warning. The explicit error-policy
observations establish the relevant promoted-warning branch, but this audit did not
run pytest or reproduce every plugin/caller filter that can override its policy.
No repository or application warning policy was changed; temporary filters existed
only inside the explicitly declared isolated audit contexts.

## 4. Evidence accounting and limits

| Observation group | Executed quantity | What it establishes |
|---|---|---|
| R/T six-shape matrix, two policies | 12 `validate` calls | Actual caught identity/context and feedback for the declared variants. |
| T context detail follow-up | 1 `validate` call | Child fields from the actual caught wrapper, without surrogate revalidation. |
| Independent R2/T2 error-policy checks | 2 `validate` calls | Full tuple equality, caught-event count, context binding, and restored trace. |
| Boundary six-schema matrix, two policies | 12 `validate` calls | Actual returned/fault branches and warning observations. |
| Fresh-subprocess default null check | 1 `validate` call | Ordinary subprocess behavior only. |
| Independent traced null pair | 2 `validate` calls | Actual caught null identity versus exception before `check_schema` entry. |
| Supplemental selector inspection | 6 direct `validator_for` calls | Selector outcomes only; not extra validation cases. |

That is 30 helper invocations plus six direct selector calls, not 36 conformance
tests. Discovery and independent checks are shown separately rather than inflating
mandatory case counts. No generation, repair, retry, cleanup, cancellation, public
accounting, or C# run was executed in this tranche. No existing test suite was run.
Existing `tests/test_schema.py` covers ordinary validation and an invalid type name,
but the inspected tests do not directly assert these R/T selected-object identities
or null warning-policy branches.

## 5. Compatibility findings and remaining gates

| Finding | Evidence / conservative disposition |
|---|---|
| R/T source predictions are confirmed at the helper boundary. | All six variants and both declared policies agree. Preserve R's leaf and T's wrapper/context; do not flatten to a common complaint. This closes a helper-identity evidence gap, not the end-to-end gate. |
| Null feedback is environment-sensitive. | Both outcomes are now observed, not just source-predicted. Preserve selector-warning failure under error policy and caught feedback under nonfatal policy. Do not force either with warning suppression, earlier validation, or a new universal SDK policy. |
| A warning promoted to exception is not already a portable error category. | Python exception identity/location is evidence. The profile must still decide its portable assessment-failure mapping and bind reference policy; no new provider retry rule follows. |
| Actual error objects are discarded by the public helper. | Ephemeral tracing obtains audit evidence but is not the approved bridge. Production/private conformance seam, isolation, order, and message/wire binding remain design gates. |
| Environment and domain are still unfrozen. | Only named shapes/resources/policies were observed. No broader malformed-schema parity, immutable environment release, C# validator suitability, or general warning behavior was proved. |

Source still places helper assessment after provider cleanup in `_run_attempt`,
uses extraction before schema validation in `_validate`, builds corrections from the
original request messages plus latest failed text, and renews local repair budget on
outer original-request retry. Only the native caught `ProviderError` path controls
provider retry/fallback; `SchemaViolationError` is outside that hierarchy. These are
source/earlier-audit facts, not newly executed histories. No policy change is proposed.

Before freeze/fixtures: approve the exact domain and environment reference, map the
selected meta-constraints to portable semantic identities, approve a nonbreaking
actual-feedback bridge, and verify assessment-only/prepared/invoked corrections,
exhaustion, correction-provider failure/restart/reset, and no-feedback controls
through the real generation core. Leave accounting/legacy-channel verification at
its existing independent gates. No implementation is authorized by this evidence.

Source anchors: `src/anyinfer/schema/validate.py:validate`,
`src/anyinfer/_client/generation.py:_validate/_run_attempt/_route_events`,
`src/anyinfer/schema/repair.py:build_repair_messages`,
installed `jsonschema/validators.py:validator_for/check_schema`,
`jsonschema/exceptions.py:_Error/SchemaError.create_from`,
`jsonschema/_keywords.py:anyOf`, and `pyproject.toml:[tool.pytest.ini_options]`.

## 6. Review and document gate

Independent cold review found no substantive contradiction or claim beyond the
evidence. It checked the call-count arithmetic, actual-object versus bridge/sent-
guidance distinction, R/T wrapper/path semantics, warning timing, internal versus
caller `anyOf`, and the linked drafts' remaining gates. Review ran no new probes.

Local links, Markdown fences/table columns, and whitespace passed across the ten
planning documents. All three resource hashes recorded here were rechecked against
raw installed bytes. Source HEAD and tracked files are unchanged. This tranche
wrote only planning Markdown under `plans/`; no fixture, implementation, external
artifact, or commit was created. The foundation checklist owns the completed audit
boxes and exact resume point.
