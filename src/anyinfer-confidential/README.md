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

See DESIGN.md §30 and the published Confidentiality Tiers doc for the
full design and the honest ceiling on what each tier guarantees.

## Running the Relay service

`app.build_app` requires a `tokens` mapping (bearer token → `tenant_id`) and refuses to
build without one. The endpoint returns the decrypted, assembled prompt, so the tenant is
derived from the presented token and never from the request body; a body `tenant_id` that
disagrees with the token is rejected. Terminate TLS in front of it, and provision routes
with `relay.load_registry` rather than a hand-rolled registration script. The full
checklist is in [the confidentiality tiers guide](../../docs/guides/confidentiality-tiers.md).
