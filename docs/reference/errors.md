# Error Catalog

Every exception AnyInfer raises, when it is raised, and what the user will see.

## The Shape of Every Error

The hierarchy is shallow, about ten classes, with rich structured fields, because callers
branch on fields far more often than on exception class:

```python
except ai.AnyInferError as error:
    error.detail          # what happened; redacted, ≤512 chars
    error.hint            # the actionable next step, when one exists
    error.provider        # which provider, when applicable
    error.phase           # configure | discover | generate | stream | validate | cleanup
    error.retryable       # would repeating this identical request help?
    error.retry_after_s   # server-advised delay, when supplied
    error.http_status     # status code, for HTTP-sourced failures
```

`detail` and `hint` always pass redaction, so no error can leak a credential no matter where
it is logged.

## The Hierarchy

```
AnyInferError
├── ConfigError               bad config, target, catalog, or a missing extra
├── CredentialError           a credential reference could not be resolved
├── ProviderError             base for anything a provider surfaced
│   ├── AuthError
│   ├── RateLimitError
│   ├── ModelNotFoundError
│   ├── ContextLengthError
│   ├── TransportError
│   ├── StreamProtocolError
│   ├── ProviderUnavailableError
│   └── UnsupportedInputError
├── SpendLimitError           a caller-set spending ceiling would be crossed
├── SchemaViolationError      validation failed after the repair budget
├── ToolLoopError             unknown tool, bad signature, or round bound exceeded
├── AllTargetsFailedError     the router exhausted every target
└── LocalRuntimeError         llama-server lifecycle, or model integrity
    └── ConfidentialExecutionError   the attested guarantee isn't available on this host
```

`ProviderError` is a distinct branch on purpose: it is exactly what the router catches and
may retry. `ConfigError`, `SchemaViolationError`, and `AllTargetsFailedError` are *not*
provider errors and propagate straight to the caller.

---

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ConfigError` :material-alert-circle:{ title="Not retryable; fix the configuration" }

**When:** an unknown target or provider, a malformed catalog, a missing required setting, or
a provider whose optional extra is not installed.

**Retryable:** no.

```
ConfigError: unknown target 'gpt-5'
  (hint: use 'provider:model' (e.g. 'anthropic:claude-sonnet-4-5'), or one of these
   aliases: large, medium, small)

ConfigError: the copilot provider requires the github-copilot-sdk extra
  (hint: pip install 'anyinfer[copilot]', then run 'copilot login')
```

### Embedding and Rerank Refusals

`embed()` and `rerank()` raise no exception types of their own: an unsupported operation,
a refused embedding fallback, or an oversized batch is a `ConfigError` whose message and
hint name the rule that refused it. The rule behind fallback refusals is
[the embedding-space safety rule](../concepts/embeddings.md#the-embedding-space-safety-rule).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `CredentialError` :material-alert-circle:{ title="Not retryable; fix the credential" }

**When:** an `env://` variable is unset, a keyring entry is missing, or the OS vault is
locked or unavailable.

**Retryable:** no.

```
CredentialError: environment variable OPENAI_API_KEY is not set
  (hint: export OPENAI_API_KEY=<your key> and retry)
```

How references resolve, and what redaction guarantees, is covered in
[credentials and redaction](../concepts/credentials.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `AuthError` :material-alert-circle:{ title="Not retryable; the same key will fail again" }

**When:** 401 or 403 from a provider: a key that is invalid, expired, or without access to
the requested model.

**Retryable:** no; the same key will fail the same way, and retrying only spends budget
a transient failure might have needed.

```
AuthError: invalid api key
  (hint: check the configured API key or credential reference)
```

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `RateLimitError` :material-alert:{ title="Retryable, honoring Retry-After" }

**When:** 429.

**Retryable:** yes, honoring `Retry-After` when longer than the computed backoff.

```
RateLimitError: provider returned HTTP 429
```

!!! tip "What to check next"
    If this recurs often, lower request concurrency or add a slower fallback target with
    [`Route.targets`](../concepts/routing.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ModelNotFoundError` :material-alert-circle:{ title="Not retryable; the model doesn't exist" }

**When:** 404, or a provider reporting the model does not exist.

**Retryable:** no.

```
ModelNotFoundError: model "qwen3:70b" not found
  (hint: pull it first: ollama pull qwen3:70b)
```

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ContextLengthError` :material-alert-circle:{ title="Not retryable; the prompt is the same size" }

**When:** the prompt exceeds the model's context window.

**Retryable:** no; the same prompt is the same size. Use `Route.context_window_targets` to
fall back to a larger model instead, or trim the prompt with
[token estimation and context budgets](../concepts/budgeting.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `TransportError` :material-alert:{ title="Retryable; no usable response arrived" }

**When:** a timeout, connection failure, or TLS error. No usable response arrived.

**Retryable:** yes. Since nothing was delivered, a retry cannot duplicate output the
consumer already saw (the boundary that makes `StreamProtocolError` different). See
[the event stream](../concepts/events.md).

```
TransportError: request to ollama timed out
  (hint: raise timeout_s, or choose a faster model)
```

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `StreamProtocolError` :material-alert-circle:{ title="Not retryable by default" }

**When:** malformed SSE/NDJSON framing, or a response exceeding `max_response_bytes`.

**Retryable:** no by default. If content had already been emitted, this is raised rather
than retried: the consumer has seen text, and silently restarting would duplicate or
contradict it. The framing and ordering guarantees are in
[the event stream](../concepts/events.md#the-ordering-guarantees).

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `ProviderUnavailableError` :material-alert:{ title="Retryable; also marks the target unhealthy" }

**When:** 5xx, or a failed health probe.

**Retryable:** yes. Also marks the target unhealthy, so the
[health gate](../concepts/routing.md#health-gating) skips it briefly.

```
ProviderUnavailableError: cannot connect to ollama: [Errno 111] Connection refused
  (hint: check the base URL and that the server is running)
```

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `UnsupportedInputError` :material-alert-circle:{ title="Not retryable; the target cannot accept this input" }

**When:** a trusted model capability proves the target cannot accept an attached input
modality (image, document, or audio). Raised before dispatch.

**Retryable:** no; the same attachment against the same target fails the same way. What
each provider accepts is covered in
[multimodal inputs](../concepts/multimodal-inputs.md).

```
UnsupportedInputError: ollama cannot project audio input (model reports no audio support)
  (hint: choose a target that supports this input form or supply supported inline bytes)
```

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `SpendLimitError` :material-alert-circle:{ title="Not retryable; the same request costs the same again" }

**When:** a request would cross a caller-set `max_request_usd` or `max_total_usd` spending
ceiling, or its cost cannot be estimated and the policy says not to spend blind. Raised
before dispatch, so nothing was sent and nothing was billed.

**Retryable:** no; deterministic by construction: the identical request refused once will
be refused again.

```
SpendLimitError: a request to anthropic:claude-sonnet-4-5 could cost 0.42, above the
per-request ceiling of 0.25
  (hint: shorten the prompt, cap max_output_tokens, or raise max_request_usd)
```

!!! tip "How to fix"
    Read `error.hint`, and inspect `error.limit_usd`, `error.spent_usd`, and
    `error.estimated_usd` for the exact numbers behind the refusal. See
    [cost and spending](../concepts/cost.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `SchemaViolationError` :material-alert-circle:{ title="Not retryable, and not a routing failure" }

**When:** the response failed validation and the repair budget is spent.

**Retryable:** no, and not a routing failure: the request reached the model and the model
answered; it answered the wrong shape.

```python
except ai.SchemaViolationError as error:
    error.raw_text     # what the model actually said
    error.errors       # ("age: 'age' is a required property",)
```

!!! tip "How to fix"
    Increase `Repair.max_attempts`, simplify the schema, inspect `error.partial` and
    `error.missing_fields`, or debug the bounded `error.raw_text`. Partial members are not
    schema-validated and no truncated value is guessed.
    See [structured output](../concepts/structured-output.md#repair).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ToolLoopError` :material-alert-circle:{ title="Not retryable" }

**When:** the model called an unregistered tool, a tool has an unsupported parameter type
(raised at *declaration* time), or `max_rounds` was exhausted.

**Retryable:** no.

```
ToolLoopError: tool 'search' parameter 'options' has unsupported type 'MyClass'
  (hint: v1 tools support str, int, float, bool, list, and dict parameters)
```

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `AllTargetsFailedError` :material-alert:{ title="Every target in the route failed or was skipped" }

**When:** every target in the route failed or was skipped.

```python
except ai.AllTargetsFailedError as error:
    for attempt in error.attempts:
        print(attempt.target, attempt.outcome, attempt.error and attempt.error.detail)
```

The `attempts` trail is the complete
[routing history](../concepts/routing.md#the-attempt-trail): every target tried, in what
order, and why each failed, including retries and health-gated skips.

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `LocalRuntimeError` :material-alert-circle:{ title="llama-server lifecycle or model integrity failure" }

**When:** llama-server failed to start, crashed, timed out becoming ready, could not be
reaped, or a model artifact failed hash verification.

```
LocalRuntimeError: llama-server exited with code 3 while loading qwen2.5-7b:
fatal: unable to load model
  (hint: the model may be incompatible with this runtime build, or the machine may
   have run out of memory)
```

The server's own log tail is included, because polling a health endpoint alone reveals
nothing about *why* it failed.

!!! tip "How to fix"
    Read the included log tail first; it usually names the real cause (OOM, an
    incompatible GGUF, a port conflict). See [the local subsystem](../concepts/local.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ConfidentialExecutionError` :material-alert-circle:{ title="Not retryable; the attested guarantee is unavailable" }

**When:** `ConfidentialExecutionAdapter.generate()` was called and
`anyinfer.local.confidential_execution_status()` reported `end_to_end=False` for this
host. The inner local adapter is never called; this fails closed, not degraded.

```
ConfidentialExecutionError: confidential execution was requested but is not available:
no attestable CPU TEE detected (SEV-SNP/TDX guest device not present)
```

!!! tip "How to fix"
    Call `confidential_execution_status()` before committing to a request, so the
    application can degrade with a message the caller sees instead of hitting this
    error mid-call. See the
    [Confidentiality Tiers guide](../guides/confidentiality-tiers.md#tier-3-attested-local-execution).

</div>

---

## Things That Look Like Bugs but Are Not

Four behaviors are reported as bugs often enough to state as intended:

- A cost of `None` when pricing is unknown. Coercing it to zero would turn a reporting
  gap into a silent accounting error; see [cost and spending](../concepts/cost.md).
- `SchemaViolationError` does not trigger fallback. The request reached the model and the
  model answered; a different provider does not fix a shape problem.
- A mid-stream protocol error after content was emitted raises rather than retries. The
  consumer has already seen text.
- An unrecognized finish reason does not crash. `FinishReason` is an open enum, and
  unknown values normalize to `"other"`.

## Handling Errors

What the router retries, in what order, and when it falls back to the next target is
covered in [routing and rate limits](../concepts/routing.md). Application-side handling
patterns are in [the integration instructions](../agents/INTEGRATION.md).
