# Context tuning v1 development evidence

This development-only profile records independent public observations of the bounded native
`ContextTuning` settings contract. It is not a release contract, does not qualify SDK.9 as a
whole, and makes no claim about reduction, request-path context policy, shared configuration,
or a new implementation registry.

`inputs.json` is the raw byte corpus: 58 ordinal-unique cases, with 57 `shared` cases and
one `native_range` boundary. It contains operands only—never expected SDK outputs, errors, or
verdicts. Python and C# observers are independently authored and call only production public
settings APIs. The checker compares their provenance and observations; it may not become a
second settings/defaults/validator implementation.

Both schemas are Draft 2020-12 structural schemas. Checker controls add strict decoded-value
rules: version, count fields, and `default_chunk_tokens` are actual JSON integers, booleans
are actual JSON booleans, and only the seven declared floating paths permit integral/decimal
numeric equivalence. Signed zero is observed explicitly.

Raw-byte SHA-256 digests at CTUNE.2a materialization:

| File | SHA-256 |
|---|---|
| `inputs.json` | `122298b5b1631317db9aa93e428faa81a00ece6da9ba9694026a57cd050b30e6` |
| `schema.json` | `f8c79b38bff6f0acbed27c74e6112806a6fa927124d56890a7b253b566ec4884` |
| `observations.schema.json` | `9ee537e939ced40c3f81ba6e19d7988daff5dc3682ed64ccef4a572334182e86` |

The README’s own hash is intentionally not embedded here; it is recorded in the CTUNE.2a
execution note after this file is complete.
