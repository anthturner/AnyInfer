# Store credentials in the OS keyring

Keep secrets out of config files and environment variables entirely.

## Install

```bash
pip install "anyinfer[keyring]"
```

## Store a secret

```bash
keyring set AnyInfer openai-api-key
```

Or from Python:

```python
import keyring

keyring.set_password("AnyInfer", "openai-api-key", "sk-...")
```

The service name is `AnyInfer`; the identifier is yours to choose.

## Reference it

```python
client = ai.Client(
    [
        ai.ProviderSettings.of("openai", api_key="credential://system/openai-api-key"),
    ]
)
```

That string is safe to commit. It names *where* the secret lives, not the secret.

## All three forms

```python
api_key = "sk-literal-value"  # in code; fine for tests, poor for config
api_key = "env://OPENAI_API_KEY"  # the usual choice for containers and CI
api_key = "credential://system/openai-api-key"  # the usual choice on a workstation
```

## Failures are actionable

```
CredentialError: no credential stored under 'openai-api-key'
  (hint: store it with keyring under service 'AnyInfer')

CredentialError: no usable OS credential store is available on this system
  (hint: configure a system keyring, or use 'env://VAR_NAME' instead)

ConfigError: the 'credential://' scheme requires the keyring extra
  (hint: pip install 'anyinfer[keyring]')
```

Headless Linux often has no usable vault; `env://` is the right answer there, and the error
says so rather than leaving you to guess.

## Custom vaults

For anything beyond the keyring — AWS Secrets Manager, HashiCorp Vault — plug your own
resolver into the chain. See
[custom resolvers](../concepts/credentials.md#custom-resolvers).

## Redaction

Every resolved secret is stripped from error details, hints, telemetry events, and recorded
test cassettes. See [credentials](../concepts/credentials.md).
