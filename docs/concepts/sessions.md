# Sessions

Every request is independent by default. That is the right default — it makes results
reproducible, routing free, and fallback safe — and it is the wrong one for a conversation,
where the provider often already has everything the next turn needs.

A **session** is how a caller says *these requests belong together*, without having to know
what any particular provider does about it.

```python
with client.session("copilot:auto") as chat:
    client.generate("Summarize this report.", session=chat)
    client.generate("Now list the risks.", session=chat)
```

## What each provider actually saves

The providers that can carry state between turns save completely different things, which is
why the handle is opaque rather than a conversation object:

| Provider | What an open session keeps | What that saves |
|---|---|---|
| [GitHub Copilot](../providers/copilot.md) | The conversation, server-side | Prior turns are not re-sent at all — fewer tokens billed, and no duplicated history |
| [llama.cpp](../providers/llama-cpp.md) | The supervised server, pinned | No model load between turns, and the KV cache the next turn reuses survives |
| [Ollama](../providers/ollama.md) | The model, resident (`keep_alive`) | No reload of several gigabytes of weights mid-conversation |

Everything else treats a session as inert.

## A session never changes an answer

It is a performance and cost optimization, and holding that line is what makes it safe to
pass one everywhere. Opening a session against a provider that cannot keep state is allowed
and does nothing:

```python
session = client.session("openai:gpt-5")
session.supported     # False
session.reuse         # 'unsupported' — and every request behaves exactly as it would have
```

## Reuse is reported, not assumed

`reuse` says what happened on the **last turn**, not what was hoped for:

| Value | Meaning |
|---|---|
| `fresh` | The provider started new state — the first turn, or one it had already expired. |
| `resumed` | The provider continued state it already held. |
| `unsupported` | Nothing was reused: this provider cannot, or that turn went somewhere else. |

## State is bound to one target

Provider state is not portable, so a session names the target it belongs to and applies
only there. If a route falls back to a different provider — or a different model on the
same one — that turn simply runs without it and reports `unsupported`:

```python
result = client.generate(
    "and the risks?",
    route=ai.Route(targets=("ollama:qwen3:8b", "openai:gpt-5")),
    session=chat,          # chat belongs to ollama:qwen3:8b
)
chat.reuse   # 'unsupported' if the fallback answered
```

Because a session already names a target, you can leave the target off entirely and it
stands in — it never overrides an explicit `target` or `route`.

## Closing is local

`close()` stops the handle being used; it does not reach out to the provider. Server-side
state expires on the provider's own schedule (Ollama's `keep_alive` timer, Copilot's
service-side session lifetime), and a library that claimed otherwise would be promising
something it cannot deliver. Closing the client itself *does* release what an adapter holds
open locally, such as a Copilot SDK session.

!!! tip "Key takeaways"
    - A session is an opaque handle, not a conversation — the library never interprets what
      a provider stores in it.
    - It never changes an answer, so passing one to a stateless provider is safe and inert.
    - `reuse` reports what the provider actually did, including when a fallback meant the
      session did not apply.

## See also

<div class="anyinfer-see-also" markdown>

- [Routing](routing.md) — what happens to a session when a route falls back.
- [The local subsystem](local.md) — why pinning a supervised server matters.
- [Capabilities and provenance](capabilities.md) — `supports_sessions` on the descriptor.

</div>
