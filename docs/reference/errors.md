# Error catalog

Every exception AnyInfer raises, when it is raised, and what the user will see.

## The shape of every error

The hierarchy is deliberately shallow (~10 classes) with rich structured fields, because
callers branch on *fields* far more often than on exception class:

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

## The hierarchy

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
│   └── ProviderUnavailableError
├── SchemaViolationError      validation failed after the repair budget
├── ToolLoopError             unknown tool, bad signature, or round bound exceeded
├── AllTargetsFailedError     the router exhausted every target
└── LocalRuntimeError         llama-server lifecycle, or model integrity
```

`ProviderError` is a distinct branch on purpose: it is exactly what the router catches and
may retry. `ConfigError`, `SchemaViolationError`, and `AllTargetsFailedError` are *not*
provider errors and propagate straight to you.

---

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ConfigError` :material-alert-circle:{ title="Not retryable; fix the configuration" }

**When:** an unknown target or provider, a malformed catalog, a missing required setting, or
a provider whose optional extra is not installed.

**Retryable:** no.

```
ConfigError: unknown target 'gpt-5'
  (hint: use 'provider:model' (e.g. 'anthropic:claude-sonnet-5'), or one of these
   aliases: large, medium, small)

ConfigError: the copilot provider requires the github-copilot-sdk extra
  (hint: pip install 'anyinfer[copilot]', then run 'copilot login')
```

!!! tip "How to fix"
    Read `error.hint`; it names the exact target spelling, alias, or install command to
    use next.

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

!!! tip "How to fix"
    Set the referenced environment variable or keyring entry, then retry. See
    [credentials and redaction](../concepts/credentials.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `AuthError` :material-alert-circle:{ title="Not retryable; the same key will fail again" }

**When:** 401 or 403 from a provider.

**Retryable:** **no**; the same key will fail the same way, and retrying only spends budget
a transient failure might have needed.

```
AuthError: invalid api key
  (hint: check the configured API key or credential reference)
```

!!! tip "What to check next"
    Verify the configured API key or credential reference is current and has access to the
    requested model.

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `RateLimitError` :material-alert:{ title="Retryable, honoring Retry-After" }

**When:** 429.

**Retryable:** yes, honoring `Retry-After` when longer than the computed backoff.

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

!!! tip "How to fix"
    Follow `error.hint`; usually pulling or deploying the model, or fixing a typo'd
    model id.

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `ContextLengthError` :material-alert-circle:{ title="Not retryable; the prompt is the same size" }

**When:** the prompt exceeds the model's context window.

**Retryable:** no; the same prompt is the same size. Use `Route.context_window_targets` to
fall back to a larger model instead.

!!! tip "How to fix"
    Add a larger-context fallback via `context_window_targets`, or trim the prompt using
    [token estimation and context budgets](../concepts/budgeting.md).

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `TransportError` :material-alert:{ title="Retryable; no usable response arrived" }

**When:** a timeout, connection failure, or TLS error. No usable response arrived.

**Retryable:** yes.

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `StreamProtocolError` :material-alert-circle:{ title="Not retryable by default" }

**When:** malformed SSE/NDJSON framing, or a response exceeding `max_response_bytes`.

**Retryable:** no by default. Note that if content had **already been emitted**, this is
raised rather than retried; the consumer has seen text, and silently restarting would
duplicate or contradict it.

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `ProviderUnavailableError` :material-alert:{ title="Retryable; also marks the target unhealthy" }

**When:** 5xx, or a failed health probe.

**Retryable:** yes. Also marks the target unhealthy, so the health gate skips it briefly.

</div>

<div class="anyinfer-error-card anyinfer-severity-high" markdown>

## `SchemaViolationError` :material-alert-circle:{ title="Not retryable, and not a routing failure" }

**When:** the response failed validation and the repair budget is spent.

**Retryable:** no, and deliberately **not** a routing failure. The request reached the model
and the model answered; it just answered the wrong shape.

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

!!! tip "How to fix"
    Register every tool the model might call, use a v1-supported parameter type, or raise
    `max_rounds`.

</div>

<div class="anyinfer-error-card anyinfer-severity-medium" markdown>

## `AllTargetsFailedError` :material-alert:{ title="Every target in the route failed or was skipped" }

**When:** every target in the route failed or was skipped.

```python
except ai.AllTargetsFailedError as error:
    for attempt in error.attempts:
        print(attempt.target, attempt.outcome, attempt.error and attempt.error.detail)
```

The `attempts` trail is the complete routing history, including retries and health-gated
skips.

!!! tip "What to check next"
    Read `error.attempts`; it names exactly which targets were tried, in what order, and
    why each failed.

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

The server's own log tail is included, because polling a health endpoint alone tells you
nothing about *why* it failed.

!!! tip "How to fix"
    Read the included log tail first; it usually names the real cause (OOM, an
    incompatible GGUF, a port conflict). See [the local subsystem](../concepts/local.md).

</div>

---

## Handling patterns

**Just show the user something useful:**

```python
except ai.AnyInferError as error:
    print(error)     # detail, plus "(hint: ...)" when there is one
```

**Distinguish configuration from runtime problems:**

```python
except (ai.ConfigError, ai.CredentialError) as error:
    sys.exit(f"configuration problem: {error}")
except ai.AllTargetsFailedError as error:
    metrics.increment("inference.exhausted")
```

**Decide whether to retry yourself:**

```python
except ai.ProviderError as error:
    if error.retryable:
        schedule_retry(after=error.retry_after_s or 5.0)
```
