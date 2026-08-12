# anyinfer-confidential

Tiers 1-2 of AnyInfer's tiered confidential-execution plan: `SealedTemplate` (encrypted-at-rest
prompt assets) and the `AnyInfer Relay` (zero-retention remote prompt assembly).

This package protects a **vendor's** prompt IP from the **customer** running the vendor's
client software on the customer's own bring-your-own-key infrastructure. It does not protect
the customer's own prompt data from AnyInfer or the vendor — BYOK already provides that.

Never imported by `anyinfer` core, and never a dependency of it.

```bash
pip install -e src/anyinfer-confidential
pip install -e "src/anyinfer-confidential[relay]"   # only if you're running the Relay service
```

See `plans/TIERED_ENCRYPTED_PLANS.md` and the published Confidentiality Tiers doc for the
full design and the honest ceiling on what each tier guarantees.
