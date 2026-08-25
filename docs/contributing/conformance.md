# The Conformance Suite

One suite, run against every adapter. It is what makes "the behavior does not change when
you change providers" a checked claim rather than an aspiration. The suite is public API,
under [`anyinfer.testing`](../reference/api/testing.md), so a
[third-party adapter](writing-an-adapter.md) certifies itself the same way the built-in
ones do.

## Division of Labor

The conformance suite proves the code matches its claims. The
[drift check](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md)
proves those claims still match upstream. Both are needed: passing tests against a
protocol that changed last month proves nothing.

## Running It

```bash
pytest tests/test_conformance.py tests/test_ollama.py -q
python workspace.py matrix                 # regenerate the published matrix
```

Each case is its own parametrized test, so a failure names the broken behavior rather than
just "conformance failed". The full case list, what each case verifies, and the three run
modes (fake-server, cassette, live) are documented on
[the conformance matrix](../reference/conformance-matrix.md). The fakes behind
fake-server mode are in-process transports, covered in
[the testing guide](testing.md#fakes-not-sockets).

## Declaring What You Cannot Do

```python
supports = Capabilities(reasoning=False, tools=False)
```

An unsupported case is reported `skipped` and renders as ➖, a declared limitation rather
than a pass, so the matrix cannot overstate a provider.

## Contributing a Cassette

Cassette coverage is the one thing here that does not scale with maintainer effort: it
needs an account on the provider, and no maintainer holds accounts on every supported
service. If you already have one, recording is a single command.

```bash
anyinfer conform groq --model llama-3.3-70b --config anyinfer.json --record tests/cassettes
```

The run makes real calls against your account and writes one cassette per scenario. From
then on the suite replays them offline, in CI, with no credentials: you spend a few cents
once, and every future run of that adapter's suite is free for everyone.

Two complementary passes stand between your traffic and the committed file. Saving a
cassette strips the known auth headers wholesale and runs every body through the
redaction registry, which removes the secrets AnyInfer was *told* about: anything
resolved through `env://`, `credential://`, or `anyinfer.credentials`. Then
`audit_cassette` re-reads the saved bytes looking for credential *shapes* it was never
told about: vendor-prefixed keys, bearer tokens written into a body, JWTs, AWS key ids,
private key material. A finding withholds that cassette rather than warning about it,
because a file left on disk after a warning is a file someone commits after skimming past
it.

The audit is heuristic and says so. It cannot find an opaque, unprefixed secret, so
**read the cassettes before committing them** — they are small, and they are your own
traffic. If the audit withholds one, the usual cause is a credential passed as a literal
rather than through a reference; route it through `anyinfer.credentials` so redaction
knows about it, and re-record.

Recording preserves any transport your config already sets, so a deployment that routes
through a proxy records what it sends through that proxy rather than bypassing it.

## Adding a Case

Add it to `CONFORMANCE_CASES` in `anyinfer/testing/conformance.py`:

```python
ConformanceCase("my_behavior", "default", "streaming", _case_my_behavior)
#                 name          scenario   capability   check
```

The check raises `AssertionError` with a message explaining what the provider got wrong. Add
a matching scenario to each harness's fake, then regenerate the matrix.

A new case usually means a new *guarantee*, so document it in the relevant concept page too.

## The Published Matrix

[docs/reference/conformance-matrix.md](../reference/conformance-matrix.md) is generated
from a real run. Never hand-edit it: a hand-maintained matrix drifts from reality and
then misleads.
