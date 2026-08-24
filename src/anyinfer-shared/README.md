# anyinfer-shared

Types shared across AnyInfer's optional confidentiality packages — currently just
`ConfidentialityReport`, a composite record of what confidentiality guarantees applied to
one call, combining facts from `anyinfer-confidential` (Tiers 1-2) and `anyinfer` core
(Tiers 3-4).

This package has no dependencies, including on `anyinfer` itself: it holds plain frozen
dataclasses, never orchestration or I/O. See DESIGN.md §30 and the
published Confidentiality Tiers doc for what each tier and field means.

```bash
pip install -e src/anyinfer-shared
```
