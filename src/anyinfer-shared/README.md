# anyinfer-shared

Types shared across AnyInfer's optional confidentiality packages — currently just
`ConfidentialityReport`, a composite record of what confidentiality guarantees applied to
one call, combining facts from `anyinfer-confidential` (Tiers 1-2) and `anyinfer` core
(Tiers 3-4).

This package has no dependencies, including on `anyinfer` itself: it holds plain frozen
dataclasses, never orchestration or I/O. `ConfidentialityReport.from_status` is the
composing entry point: it takes core's attestation status for Tiers 3-4 and the Tier 1-2
facts only the application knows.

Field-by-field signatures are on the
[confidentiality add-ons API reference](https://anyinfer.dev/reference/api/confidential/),
and the [Confidentiality Tiers guide](https://anyinfer.dev/guides/confidentiality-tiers/)
explains what each tier means. (DESIGN.md §30 is the internal record behind both.)

```bash
pip install -e src/anyinfer-shared
```
