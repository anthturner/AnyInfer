# Why and When to Use AnyInfer

Most libraries in this space solve provider switching: one function, many APIs, one
response shape. That is a real problem and several tools solve it well. AnyInfer is built
for the problem that starts immediately afterward, when an application has to be correct
about what it sent, what it got back, what it cost, and what quietly did not happen.

An OpenAI-shaped request does not make providers behave alike. One supports a JSON schema
natively, one has a grammar, one only has "JSON mode", one drops your `top_p` without
saying so. One reports cached tokens inside the prompt total, one beside it. One tells
you its context window, one guesses, one says nothing. A library that normalizes the
syntax and leaves the behavior to you has moved the problem, not solved it. AnyInfer
normalizes the behavior and reports every place it could not.

This page argues both directions: what is genuinely unusual here, and when a smaller
tool is the better boundary.

## Five Things That Are Unusual

### 1. You Can Unit-Test Your Integration's Failure Paths, Offline

Inference code has behavior worth testing: it falls back when a provider is down, it
repairs a malformed structured answer, it reduces a corpus to fit. Testing that normally
means mocking your own wrapper, which mostly tests the mock, or provoking a real outage.
The test kit ships with the library, so your fallback chain has a real test with no
credentials and no network:

```python
from anyinfer.testing import ScriptedFailure, ScriptedModel, ScriptedProvider

provider = ScriptedProvider(
    "acme",
    [
        ScriptedModel("flaky", failures=(ScriptedFailure(status=503, retry_after_s=0.0),)),
        ScriptedModel(
            "structured",
            structured={"answer": "valid on the second try"},
            failures=(ScriptedFailure(kind="malformed-json"),),
        ),
    ],
)
```

Five failure kinds are declarable (an HTTP status with `Retry-After`, a stream cut
mid-event, a body that will not validate, a read timeout, and a content-policy refusal),
and each reaches a different part of the core. These are the failures you cannot
schedule against a real provider, and they are exactly the ones your error handling is
written for. See [test your application offline](guides/testing-your-app.md).

### 2. Every Number Says Where It Came From

A context window you read from a table and a context window the provider just told you
are not the same fact, and code that cannot tell them apart will eventually gate a
request on a guess.

```python
budget.context_window  # Sourced(200000, 'catalog')
budget.context_window  # Sourced(8192, 'discovered')
budget.context_window  # None, and it stays None
```

Five provenances layer from weakest to strongest (`default`, `catalog`, `discovered`,
`probed`, `override`), and a weaker source never displaces a stronger one. Only trusted
provenance may refuse a request pre-dispatch. The same rule governs money:
`usage.cost_usd` is a `Decimal` or `None`, and `None` means unknown, never zero. See
[capabilities and provenance](concepts/capabilities.md).

### 3. Portability Is a Test Result, Not a Claim

106 providers is inventory, not a feature; the useful part is knowing which of them does
what you need. The [conformance matrix](reference/conformance-matrix.md) is generated
from real suite runs: every cell is one test case that executed against that adapter,
and a `➖` is a declared limitation, not a pass. Providers without rows stay empty
rather than turning missing evidence into a claim.

Underneath it, 20
[contract snapshots](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md)
record exactly which upstream endpoints, fields, framing, and error shapes each adapter
depends on, each dated, with a
[drift-check procedure](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md)
that audits them against current provider documentation. Writing
[your own adapter](guides/custom-providers.md) puts it on the same footing:
`anyinfer conform` runs the suite and emits its matrix row.

### 4. A Local Model Is a Target, Not a Separate Product

```python
client.generate(prompt, target="anthropic:claude-sonnet-4-5")
client.generate(prompt, target="llama-cpp:qwen3-8b-q4-k-m")  # one string changed
```

If the weights are not there yet, the second call acquires a pinned, hash-verified
artifact, picks a runtime for the detected hardware, tunes the launch flags for the
memory actually available, starts `llama-server` on loopback, waits for readiness,
serves the request, and evicts the model when idle. No separate daemon to install or
operate. An already-running Ollama, LM Studio, or vLLM is equally a target, and both
kinds sit in the same fallback chain with the same event stream, usage normalization,
and structured-output contract. See [run a model locally](guides/local-inference.md).

### 5. Context Fit Is Decided Before You Pay for It

```python
budget = client.budget(messages, target="anthropic:claude-sonnet-4-5")
budget.remaining_tokens  # what is left for context
budget.fits  # True / False / None; None means the window is unknown

reduction = context.select(documents, query, max_tokens=budget.remaining_tokens)
reduction.summary()  # what was sent, what was dropped, and what bound the decision
```

The same target capabilities drive budgeting, reduction, pre-dispatch refusal, cost
estimation, and context-overflow routing, so they all use the same facts. Reduction
reports its omissions rather than quietly truncating. See
[context budgets](concepts/budgeting.md) and
[context reduction](concepts/context-reduction.md).

## When a Smaller Tool Is the Better Boundary

Provider count is not a reason to add a dependency. Use AnyInfer when the application
needs to own a hybrid inference runtime; use the smaller tool when it already solves
your whole problem:

| Your actual requirement | Usually the better boundary |
|---|---|
| Call one provider | That provider's client or HTTP API |
| Switch among cloud APIs with one Python function | A focused provider client such as [any-llm](https://github.com/mozilla-ai/any-llm) or [aisuite](https://github.com/andrewyng/aisuite) |
| Centralize credentials, virtual keys, quotas, organization spend, and admin policy | A gateway such as [LiteLLM](https://github.com/BerriAI/litellm), [Bifrost](https://github.com/maximhq/bifrost), or [Portkey](https://github.com/Portkey-AI/gateway) |
| Operate a dedicated local-model platform | [Ollama](https://github.com/ollama/ollama), [LM Studio](https://lmstudio.ai/), or [LocalAI](https://github.com/mudler/LocalAI) |
| Run high-throughput GPU serving infrastructure | [vLLM](https://github.com/vllm-project/vllm) or another serving platform |
| Build semantic retrieval over a changing corpus | A retrieval or vector-index system; pass its approved results into AnyInfer if you still need the hybrid runtime |
| Ship one application-owned route spanning cloud and a managed local fallback | AnyInfer |

These tools compose. A gateway in front of AnyInfer is a reasonable architecture, and so
is AnyInfer calling an Ollama you already operate. AnyInfer earns its place only when
removing the boundary between them makes the application simpler or its behavior more
reliable.

Some things here are support, not differentiators: a long provider list, an
OpenAI-compatible sidecar, basic retry and fallback, or calling an already-running local
endpoint. Integrators need all of those, and many tools have them. The reason to pick
AnyInfer is the runtime and correctness contract around them.

## Where It Sits Among the Alternatives

The columns are categories of tool, not specific products: a category claim can be
checked against what the category is for, while a product claim goes stale the week it
is written. Snapshot date: 2026-08-09. When choosing against a specific tool, verify
that tool's current behavior rather than trusting a generalization here.

| | **AnyInfer** | Provider-switching client | Hosted gateway / proxy | Local-model server | Agent framework |
|---|---|---|---|---|---|
| What your code holds | Typed event stream | An OpenAI-shaped response | OpenAI wire format | OpenAI wire format | The framework's abstraction |
| Runs in your process | Yes | Yes | No; a service you operate | No; a service you operate | Yes |
| Hosted **and** managed-local in one fallback chain | Yes | Hosted, usually | Across endpoints you already run | Local only | Whatever its client does |
| Acquires, verifies, and supervises a local model process | Yes (`llama.cpp`) | No | No | Yes; that is its job | No |
| Capability provenance, tri-state cost, degradation events | Yes | Not typically | Not typically | N/A | Varies |
| Structured output validated client-side, with bounded repair | Yes | Varies | Passes the provider's mode through | Passes through | Commonly yes |
| Test kit, per-adapter conformance matrix, dated contract snapshots | Yes | Rare | Rare | N/A | Rare |
| Mandatory dependencies | 2 | Varies | N/A | N/A | Typically many |
| Central keys, org quotas, admin plane | **No; use a gateway** | No | Yes | No | No |
| Retrieval / vector index / corpus persistence | **Opt-in add-on only** ([`anyinfer-store`](guides/vector-store.md), small-scale) | No | No | No | Often yes |
| Prompt templates, chains, agents | **No** | No | No | No | Yes; that is its job |
| High-throughput GPU serving | **No** | No | No | Some | No |

The last four rows matter most: AnyInfer is a runtime, not a platform, and the tools in
those columns are boundaries to compose with, not competitors.

## Check the Claims Yourself

Nothing on this page requires taking a documentation page's word for it:

```bash
pip install anyinfer
anyinfer init                       # what this machine can already use, written to a file
anyinfer providers --json           # every provider and the fields it needs
anyinfer verify --config anyinfer.json    # does each target actually answer?
anyinfer run "..." --dry-run --target ollama:qwen3:8b   # cost and fit, nothing spent
```

`anyinfer verify` sends a real, tiny request, because a credential can be valid for a
model listing and useless for inference, and it distinguishes *unreachable* from
*reachable but could not hold the requested shape*, which need different fixes. Nothing
requires an account: the [demo app](guides/demo-app.md) runs entirely offline against
in-process fakes, and every code example in this documentation is executed in CI against
those same fakes, so none of it can quietly rot.

## Confidential Execution

BYOK inference protects your customer's data from you; it does nothing to protect your
prompt templates and orchestration IP from a customer who owns the machine they run on.
AnyInfer ships a four-tier ladder for that problem, from encrypted-at-rest templates up
to attested execution in a trusted environment with signed-model verification, each
tier stating exactly what it does and does not guarantee. See
[confidentiality tiers](guides/confidentiality-tiers.md).

## Who This Is For

It fits an application that ships: a desktop tool, a developer tool, an offline-capable
service, a distributable Python product. That is, something that needs a cloud route and
a local route to behave the same way, that has to explain its costs, and whose inference
code deserves tests. It does not fit a notebook experiment, a single-provider script, or an
organization looking for a central control plane; the table above names better-shaped
tools for those.

## See Also

<div class="anyinfer-see-also" markdown>

- [Quickstart](guides/quickstart.md): install to first result.
- [Integrate AnyInfer](guides/README.md): choosing between the SDK, CLI, and sidecar.
- [Concepts](concepts/README.md): the eighteen ideas the API follows from.

</div>
