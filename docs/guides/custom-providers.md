# Add your own provider

Your company runs an internal LLM gateway. Your team fine-tunes models behind a private
endpoint. A provider AnyInfer does not ship exists and you need it today. None of these
require a fork: a provider is a small installable package, and once it is installed,
`yourprovider:model` targets resolve everywhere — the Python API, the command line, the
sidecar, and any config UI built on the setup spec.

## Do you need an adapter at all?

If your endpoint speaks `/chat/completions` and differs only by URL, authentication
spelling, and a few quirks, you do not. Point the built-in OpenAI-compatible provider at it:

```python
client = ai.Client([
    ai.ProviderSettings.of(
        "openai-compat",
        base_url="https://llm.internal.example/v1",
        api_key="env://INTERNAL_LLM_KEY",
    )
])
```

Write an adapter when there is real protocol translation to do — a different request shape,
a different streaming framing, or discovery that reports something the OpenAI listing
cannot express.

## Scaffold it

```bash
anyinfer conform acme --scaffold ./acme-anyinfer
```

That writes a package that already imports, registers, and resolves:

```
acme-anyinfer/
  acme_anyinfer/__init__.py     the descriptor and its entry point
  acme_anyinfer/adapter.py      the four methods to fill in
  contracts/acme.md             the protocol snapshot to record what you depend on
  tests/test_conformance.py     certification, ready to point at your endpoint
  pyproject.toml                the entry point and your capability declarations
  README.md
```

## Write the four methods

An adapter exposes exactly `list_models`, `health`, `generate`, and `aclose`. `generate`
yields normalized events; everything else is the core's job:

> Retry, fallback, health gating, schema validation and repair, first-token timing, usage
> normalization, cost, telemetry, and redaction live in AnyInfer's core. If you find
> yourself adding control flow to an adapter, it belongs in the core instead — and it is
> probably already there.

That constraint is what makes an adapter small. It is also what makes your provider behave
identically to every built-in one without you implementing any of it.

## Declare what your provider needs

The descriptor's `ProviderSetupSpec` is how a configuration UI renders your provider
without knowing which provider it is: which fields to prompt for, which have sensible
defaults, which are credentials, and which environment variable each conventionally comes
from. Fill it in and every AnyInfer-based application can configure your provider.

## Certify it

```bash
anyinfer conform acme --model acme-large
```

```
acme

  ✅  list_models
  ✅  health
  ✅  non_streaming
  ✅  streaming
  ❌  usage             usage must report output tokens
  ➖  reasoning         declared unsupported

  12 passed, 1 failed, 1 declared unsupported
```

This is the same suite the built-in adapters run. Cases your provider genuinely cannot
support are declared in your `pyproject.toml`, where they show as ➖ rather than as
failures:

```toml
[tool.anyinfer.conformance]
reasoning = false     # no reasoning channel on this API
retry_after = false   # rate limiting cannot be provoked on demand
```

Declaring them in the project file rather than on the command line keeps the claim
reviewable — "what we do not support" is checked in, not typed once on a bad day.

The command exits non-zero on any failure, so your own CI can gate on it. Add
`--markdown-row` for a pasteable conformance-matrix row, or `--json` for a machine-readable
report.

## Record what you depend on

`contracts/acme.md` is the snapshot of exactly which upstream details your adapter relies
on: endpoints, auth headers, version pins, fields sent and read, streaming framing, and
error-mapping inputs. It exists so that when the provider changes something, you can tell —
by comparing the snapshot against their current documentation rather than by waiting for a
production failure.

## Install and use it

```bash
pip install -e ./acme-anyinfer
```

```python
client = ai.Client([ai.ProviderSettings.of("acme", api_key="env://ACME_API_KEY")])
client.generate("hello", target="acme:acme-large")
```

Nothing in the application changed. If your package fails to load — a bad import, an id
that collides with a built-in — `anyinfer doctor` says so by name, rather than leaving your
provider mysteriously absent.
