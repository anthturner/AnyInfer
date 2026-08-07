# Errors

A shallow hierarchy with structured fields (`provider`, `phase`, `retryable`,
`http_status`, `detail`, `hint`) — `detail` is bounded and redacted, `hint` is the
actionable next step. The prose catalog with examples lives in
[the error reference](../errors.md).

<div class="anyinfer-api-block" markdown>

::: anyinfer.AnyInferError

::: anyinfer.Phase

::: anyinfer.ConfigError

::: anyinfer.CredentialError

::: anyinfer.AuthError

::: anyinfer.ProviderError

::: anyinfer.ProviderUnavailableError

::: anyinfer.RateLimitError

::: anyinfer.ModelNotFoundError

::: anyinfer.ContextLengthError

::: anyinfer.TransportError

::: anyinfer.StreamProtocolError

::: anyinfer.SchemaViolationError

::: anyinfer.ToolLoopError

::: anyinfer.AllTargetsFailedError

::: anyinfer.LocalRuntimeError

</div>
