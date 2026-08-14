# Why AnyInfer

Most libraries in this space solve *provider switching*: one function, many APIs, one
response shape. That is a real problem and several tools solve it well. AnyInfer is built
for the problem that starts immediately afterwards, when an application has to be correct
about what it sent, what it got back, what it cost, and what quietly did not happen.

The short version: **an OpenAI-shaped request does not make providers behave alike.** One
supports a JSON schema natively, one has a grammar, one only has "JSON mode", one silently
drops your `top_p`. One reports cached tokens inside the prompt total, one reports them
beside it. One tells you its context window, one guesses, one says nothing. A library that
normalizes the *syntax* and leaves the *behaviour* to you has moved the problem, not solved
it. AnyInfer normalizes the behaviour and reports every place it could not.

---

## Five things that are actually unusual

### 1. You can unit-test your integration's failure paths, offline

Your application's inference code has behaviour worth testing: it falls back when a
provider is down, it repairs a malformed structured answer, it reduces a corpus to fit.
Testing that normally means mocking your own wrapper, which mostly tests the mock, or
provoking a real outage.

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

Five failure kinds are declarable: an HTTP status with `Retry-After`, a stream cut
mid-event, a body that will not validate, a read timeout, and a content-policy refusal. Each
each reaches a different part of the core. These are the failures you cannot schedule
against a real provider, and they are exactly the ones your error handling is written for.

→ [Test your application offline](guides/testing-your-app.md)

### 2. Every number says where it came from

A context window you read from a table and a context window the provider just told you are
not the same fact, and code that cannot tell them apart will eventually gate a request on a
guess.

```python
budget.context_window  # Sourced(200000, 'catalog')
budget.context_window  # Sourced(8192, 'discovered')
budget.context_window  # None, and it stays None
```

Five provenances are layered from weakest to strongest: `default`, `catalog`, `discovered`,
`probed`, and `override`. A weaker source never displaces a stronger one. Only trusted
provenance is allowed to refuse a request pre-dispatch. Nothing is ever silently upgraded
from "we assumed" to "we know".

The same rule governs money: `usage.cost_usd` is a `Decimal` or `None`, and `None` means
*unknown*, never zero. Treating an unpriced call as free is the most common accounting bug
in this category, and it is unrepresentable here.

→ [Capabilities and provenance](concepts/capabilities.md)

### 3. Portability is a test result, not a claim

103 providers is inventory, not a feature. The useful part is knowing which of them does
what you need. AnyInfer runs the same suite against each adapter and publishes the results,
including the gaps.

The [conformance matrix](reference/conformance-matrix.md) is generated from real runs, and
every cell is one parametrized test case that executed against that adapter. A `➖` is a
declared limitation, not a pass. Ten providers carry rows today and the rest are
uncertified. The matrix leaves those rows empty instead of turning missing evidence into a
claim.

Underneath it, 20 [contract snapshots](https://github.com/anthturner/AnyInfer/blob/main/contracts/README.md)
record exactly which upstream endpoints, fields, framing, and error shapes each adapter
depends on, each with the date it was last verified, including snapshots that say plainly
"not yet verified against live provider documentation". A
[drift-check procedure](https://github.com/anthturner/AnyInfer/blob/main/contracts/DRIFT-CHECK.md)
audits them against current provider documentation. When an adapter's wire behaviour
changes, its snapshot changes in the same commit.

Writing your own adapter puts it on the same footing: `anyinfer conform` runs the suite
against it and emits its matrix row.

→ [The conformance matrix](reference/conformance-matrix.md) ·
[Add your own provider](guides/custom-providers.md)

### 4. A local model is a target, not a separate product

```python
client.generate(prompt, target="anthropic:claude-sonnet-4-5")
client.generate(prompt, target="llama-cpp:qwen3-8b-q4-k-m")  # one string changed
```

The second call, if the weights are not there yet, will acquire a pinned and hash-verified
artifact, pick a runtime variant for the detected hardware, tune the launch flags for the
memory actually available, start `llama-server` on loopback, wait for readiness, serve the
request, and evict the model when it has been idle long enough. No separate daemon to
install or operate.

An already-running Ollama, LM Studio, or vLLM is equally a target when that is the boundary
you want. What is unusual is that both are the same call, in the same fallback chain, with
the same event stream, the same usage normalization, and the same structured-output
contract.

→ [Run a model locally, end to end](guides/local-inference.md)

### 5. Context fit is decided before you pay for it

```python
budget = client.budget(messages, target="anthropic:claude-sonnet-4-5")
budget.remaining_tokens  # what is left for context
budget.fits  # True / False / None; None means the window is unknown
budget.estimated_cost  # a range, or None

reduction = context.select(documents, query, max_tokens=budget.remaining_tokens)
reduction.summary()  # what was sent, what was dropped, and what bound the decision
```

The same target capabilities drive budgeting, reduction, pre-dispatch refusal, cost
estimation, and context-overflow routing. They all use the same facts. Reduction reports
its omissions rather than quietly truncating, because a prompt that lost your most
important file without saying so is worse than one that did not fit.

→ [Token estimation and context budgets](concepts/budgeting.md) ·
[Context reduction](concepts/context-reduction.md)

---

## Where it sits among the alternatives

**Read this table carefully, including its limits.** The columns are *categories of tool*,
not specific products, because a category claim can be checked against what the category is
for, while a product claim goes stale the week after it is written. Individual products
vary widely and move fast. **Snapshot date: 2026-08-09.** If you are choosing between
AnyInfer and a specific tool, verify that tool's current behaviour rather than trusting a
generalization here, and read [when to use AnyInfer](guides/when-to-use.md), which argues
the other side.

| | **AnyInfer** | Provider-switching client | Hosted gateway / proxy | Local-model server | Agent framework |
|---|---|---|---|---|---|
| What your code holds | Typed event stream | An OpenAI-shaped response | OpenAI wire format | OpenAI wire format | The framework's abstraction |
| Runs in your process | Yes | Yes | No; it is a service you operate | No; it is a service you operate | Yes |
| Hosted **and** managed-local in one fallback chain | Yes | Hosted, usually | Across endpoints you already run | Local only | Whatever its client does |
| Acquires, verifies, and supervises a local model process | Yes (`llama.cpp`) | No | No | Yes; that is its job | No |
| Capability values carry provenance | Yes | Not typically | Not typically | N/A | Not typically |
| Unknown cost is `None`, never `0` | Yes | Varies | Varies | N/A | Varies |
| Structured output validated client-side, with bounded repair | Yes | Varies | Passes the provider's mode through | Passes through | Commonly yes |
| Dropped parameters and weakened mechanisms are reported | Yes, as typed events | Rare | Rare | Rare | Rare |
| Ships a test kit for *your* failure paths | Yes | Rare | Rare | N/A | Varies |
| Per-adapter conformance matrix from executed tests | Yes (10 certified so far) | Rare | Rare | N/A | Rare |
| Dated upstream contract snapshots + drift audit | Yes (20) | Rare | Rare | Rare | Rare |
| Mandatory dependencies | 2 | Varies | N/A | N/A | Typically many |
| Central keys, org quotas, admin plane | **No; use a gateway** | No | Yes | No | No |
| Embeddings and reranking as typed, routed inference ops | Yes | Varies | Varies | Varies | Often via a plugin |
| Retrieval / vector index / corpus persistence | **Opt-in add-on only** ([`anyinfer-store`](guides/vector-store.md), small-scale) | No | No | No | Often yes |
| Prompt templates, chains, agents | **No** | No | No | No | Yes; that is its job |
| High-throughput GPU serving | **No** | No | No | Some | No |

The last three rows are the important ones. AnyInfer is a runtime, not a platform, and the
tools in those columns are not competitors. They are boundaries to compose with. A gateway
in front of AnyInfer is a reasonable architecture. So is AnyInfer calling
an Ollama you already operate.

---

## Check every claim on this page yourself

The point of provenance, conformance, and contract snapshots is that you do not have to
take a documentation page's word for anything, including this one:

```bash
pip install anyinfer
anyinfer init                       # what this machine can already use, written to a file
anyinfer providers --json           # every provider and the fields it needs
anyinfer verify --config anyinfer.json    # does each target actually answer?
anyinfer run "..." --dry-run --target ollama:qwen3:8b   # cost and fit, nothing spent
```

`anyinfer verify` is the definitive check. It sends a real, tiny request, because a credential
can be valid for a model listing and useless for inference, and it distinguishes
*unreachable* from *reachable but could not hold the requested shape*, which need
completely different fixes.

Nothing on this page requires an account. The [demo app](guides/demo-app.md) runs entirely
offline against in-process fakes, and every code example in this documentation is executed
in CI against those same fakes, so none of it can quietly rot.

---

## Confidential execution: an honestly-tiered check nobody else ships

BYOK inference has an asymmetry nobody selling a client-side SDK talks about: your
application's prompts, prompt templates, and orchestration logic run entirely on
infrastructure your customer controls. You can protect their data from you — that part is
solved, and it's most of what "BYOK" already means. Protecting *your own* prompt engineering
and orchestration IP from a customer who owns the machine it runs on is a fundamentally
harder problem, and for most of the industry the honest answer is still "you can't, so
nobody architects for it."

AnyInfer now ships four tiers that raise the cost of extraction up to the one point where a
real cryptographic guarantee is possible: encrypted-at-rest prompt templates (Tier 1), a
zero-retention remote assembly service so orchestration logic never ships to the client at
all (Tier 2), and — the interesting one — a **portable capability check** that tells your
application, on whatever hardware a customer actually has, whether local inference can run
inside an attested trusted execution environment right now, with no silent downgrade when it
can't (Tier 3), plus a verification layer proving the model weights that ran are the exact
ones you signed (Tier 4). The underlying hardware capability isn't novel — AMD SEV-SNP, Intel
TDX, and NVIDIA's confidential-computing GPUs already exist, and cloud vendors already sell
attested inference as a service. What we could not find anywhere else is that capability
exposed as one function inside a multi-provider BYOK library, honest about exactly what it
can and cannot promise on the hardware in front of it. See the full
[Confidentiality tiers](guides/confidentiality-tiers.md) guide for what each tier actually
guarantees, what it costs, and — just as important — what it deliberately does not claim
yet (GPU-offload attestation and cryptographic quote verification are both real gaps, named
on that page rather than glossed over).

## Who this is for

It fits an application that ships: a desktop tool, a developer tool, an offline-capable
service, a distributable Python product. Something that needs a cloud route and a local
route to behave the same way, that has to explain its costs, and whose inference code
deserves tests.

It does not fit a notebook experiment, a single-provider script, or an organization looking
for a central control plane. Those have better-shaped tools, and
[when to use AnyInfer](guides/when-to-use.md) names them.

## Continue

- [When to use AnyInfer](guides/when-to-use.md): the same question, argued against
- [Quickstart](guides/quickstart.md): install to first result
- [Choosing an integration path](guides/integration-paths.md): SDK, CLI, or sidecar
