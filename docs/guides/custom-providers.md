# Add Your Own Provider

A provider AnyInfer does not ship is not a fork: a provider is a small installable
package, and once it is installed, `yourprovider:model` targets resolve everywhere: the
Python API, the command line, the sidecar, and any config UI built on the setup spec.

## Do You Need an Adapter at All?

If your endpoint speaks `/chat/completions` and differs only by URL, authentication
spelling, and a few quirks, you do not. Point the built-in
[OpenAI-compatible provider](../providers/openai-compat.md) at it:

```python
client = ai.Client(
    [
        ai.ProviderSettings.of(
            "openai-compat",
            base_url="https://llm.internal.example/v1",
            api_key="env://INTERNAL_LLM_KEY",
        )
    ]
)
```

Write an adapter when there is real protocol translation to do: a different request shape,
a different streaming framing, or discovery that reports something the OpenAI listing
cannot express.

## Scaffold It

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

## Write the Four Methods

An adapter exposes exactly `list_models`, `health`, `generate`, and `aclose`. `generate`
yields normalized events; everything else is the core's job:

> Retry, fallback, health gating, schema validation and repair, first-token timing, usage
> normalization, cost, telemetry, and redaction live in AnyInfer's core. If you find
> yourself adding control flow to an adapter, it belongs in the core instead, and it is
> probably already there.

That constraint is what makes an adapter small. It is also what makes your provider behave
identically to every built-in one without you implementing any of it. The
[adapter walkthrough](../contributing/writing-an-adapter.md) covers each method's contract
in detail, and what your models support flows through the same
[capabilities](../concepts/capabilities.md) system the built-ins use; declare what you
know and leave the rest unknown.

## Declare What Your Provider Needs

The descriptor's `ProviderSetupSpec` is what allows a configuration UI to render your
provider without knowing which provider it is: which fields to prompt for, which have
sensible defaults, which are credentials, and which environment variable each
conventionally comes from. Fill it in and every AnyInfer-based application can configure your provider.

Declare `SetupField.env_var` on any field with a conventional variable: the bare name,
`"ACME_API_KEY"`, not the `env://` reference form. It is the machine-readable half of what
`placeholder` says in prose, and it is what allows `anyinfer init` to find your provider
already usable on somebody's machine, and a config UI to say "we found this in your
environment", without either of them parsing an example sentence.

## Certify It

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
```

This is the same [conformance suite](../contributing/conformance.md) the built-in adapters
run, and their results are published as the
[conformance matrix](../reference/conformance-matrix.md). Cases your provider genuinely
cannot support are declared in your `pyproject.toml`, where they show as ➖ rather than as
failures:

```toml
[tool.anyinfer.conformance]
reasoning = false     # no reasoning channel on this API
retry_after = false   # rate limiting cannot be provoked on demand
```

Declaring them in the project file rather than on the command line keeps the claim
reviewable: "what we do not support" is checked in, not typed once on a bad day.

The command exits non-zero on any failure, so your own CI can gate on it. Add
`--markdown-row` for a pasteable conformance-matrix row, or `--json` for a machine-readable
report.

## Record What You Depend On

`contracts/acme.md` is the snapshot of exactly which upstream details your adapter relies
on: endpoints, auth headers, version pins, fields sent and read, streaming framing, and
error-mapping inputs. It exists so that when the provider changes something, you can tell —
by comparing the snapshot against their current documentation rather than by waiting for a
production failure. The in-tree adapters keep the same snapshots under `contracts/`,
written by the procedure in
[`contracts/NEW-PROVIDER.md`](https://github.com/anthturner/AnyInfer/blob/main/contracts/NEW-PROVIDER.md).

## Install and Use It

```bash
pip install -e ./acme-anyinfer
```

```python
client = ai.Client([ai.ProviderSettings.of("acme", api_key="env://ACME_API_KEY")])
client.generate("hello", target="acme:acme-large")
```

Nothing in the application changed. If your package fails to load (a bad import, an id
that collides with a built-in), `anyinfer doctor` says so by name, rather than leaving your
provider mysteriously absent.

!!! tip "Key Takeaways"
    - An endpoint that speaks `/chat/completions` needs no adapter; `openai-compat` with a
      `base_url` covers it.
    - An adapter is four methods that translate protocol. Retry, validation, timing,
      cost, telemetry, and redaction stay in the core, which is why your provider behaves
      like every built-in one.
    - Conformance cases you cannot support are declared in `pyproject.toml`, so the claim
      is checked in and reviewable, and CI can gate on the suite's exit code.
    - The contract snapshot records the upstream details you depend on, so provider drift
      is detectable by comparison instead of by production failure.

## See Also

<div class="anyinfer-see-also" markdown>

- [Writing an adapter](../contributing/writing-an-adapter.md): the four methods in full.
- [Conformance](../contributing/conformance.md): what the certification suite checks and
  why.
- [Conformance matrix](../reference/conformance-matrix.md): where the built-in adapters
  stand.
- [OpenAI-compatible provider](../providers/openai-compat.md): the no-adapter path.

</div>
