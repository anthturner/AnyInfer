using AnyInfer.Schema;
using System.Text;

namespace AnyInfer;

/// <summary>Contains a safe, serializable summary of an AnyInfer exception.</summary>
/// <remarks>
/// <see cref="AnyInferException.Snapshot"/> produces this summary, and telemetry events and run
/// manifests carry it in place of the exception object. It omits the category, hint, retry delay,
/// and native inner exception.
/// </remarks>
/// <param name="TypeName">Unqualified runtime type name of the summarized exception, such as <c>RateLimitException</c>.</param>
/// <param name="Provider">Provider instance identifier associated with the failure, or <see langword="null"/> when unknown.</param>
/// <param name="Phase">Lifecycle phase that failed, such as <c>generate</c> or <c>stream</c>, or <see langword="null"/> when unknown.</param>
/// <param name="Retryable">Whether the failed operation may be retried.</param>
/// <param name="HttpStatus">HTTP status code of the failed response, or <see langword="null"/> when none applies.</param>
/// <param name="Detail">Diagnostic text. <see cref="AnyInferException.Snapshot"/> supplies the redacted detail, or the message when no detail was given, truncated to 512 Unicode scalar values; a directly constructed value is stored as given.</param>
public sealed record ErrorInfo(
    string TypeName,
    string? Provider,
    string? Phase,
    bool Retryable,
    int? HttpStatus,
    string? Detail);

/// <summary>Base exception for typed AnyInfer failures with provider and retry metadata.</summary>
/// <remarks>
/// The message, <see cref="Category"/>, <see cref="Phase"/>, <see cref="Provider"/>,
/// <see cref="Detail"/>, and <see cref="Hint"/> are redacted against the secrets registered with
/// <see cref="Redaction"/> when the exception is constructed, and <see cref="Detail"/> is also
/// truncated to 512 Unicode scalar values. <see cref="NativeInner"/> is never redacted, so its own
/// message and properties can still contain sensitive values. <see cref="ToString"/> redacts the
/// complete rendering, including the inner exception chain, each time it is called.
/// </remarks>
public class AnyInferException : Exception
{
    private const int MaximumDetailLength = 512;

    /// <summary>Initializes an AnyInfer exception while preserving the original native exception.</summary>
    /// <param name="message">Failure message; registered secrets are redacted before it becomes <see cref="Exception.Message"/>.</param>
    /// <param name="category">Stable semantic failure category, such as <c>auth</c> or <c>rate_limit</c>; stored redacted in <see cref="Category"/>.</param>
    /// <param name="retryable">Whether retrying the failed operation may succeed.</param>
    /// <param name="phase">Lifecycle phase that failed, such as <c>configure</c>, <c>generate</c>, <c>stream</c>, or <c>validate</c>; <see langword="null"/> when unknown.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, stored as given, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when the failure is not tied to one.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, kept unchanged as both <see cref="Exception.InnerException"/> and <see cref="NativeInner"/>; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> or <paramref name="category"/> is <see langword="null"/>.</exception>
    public AnyInferException(
        string message,
        string category,
        bool retryable,
        string? phase,
        double? retryAfterS = null,
        int? httpStatus = null,
        string? provider = null,
        string? detail = null,
        string? hint = null,
        Exception? nativeInner = null)
        : base(Sanitize(message), nativeInner)
    {
        ArgumentNullException.ThrowIfNull(category);
        Category = Redaction.Redact(category);
        Retryable = retryable;
        Phase = RedactMetadata(phase);
        RetryAfterS = retryAfterS;
        HttpStatus = httpStatus;
        Provider = RedactMetadata(provider);
        Detail = detail is null ? null : Bound(detail);
        Hint = hint is null ? null : Redaction.Redact(hint);
        NativeInner = nativeInner;
    }

    /// <summary>Gets the stable semantic failure category, such as <c>auth</c>, <c>rate_limit</c>, <c>config</c>, or <c>schema_violation</c>.</summary>
    public string Category { get; }

    /// <summary>Gets whether the failed operation may be retried.</summary>
    public bool Retryable { get; }

    /// <summary>Gets the lifecycle phase that failed, such as <c>generate</c> or <c>stream</c>, when known.</summary>
    public string? Phase { get; }

    /// <summary>Gets the server supplied retry delay in seconds, when known.</summary>
    /// <remarks>Route retries use it as a lower bound for the next backoff delay, which remains capped by <see cref="Retry.BackoffMaxS"/>.</remarks>
    public double? RetryAfterS { get; }

    /// <summary>Gets the HTTP status code of the failed response, when one was received.</summary>
    public int? HttpStatus { get; }

    /// <summary>Gets the provider identifier associated with the failure, when known.</summary>
    public string? Provider { get; }

    /// <summary>Gets the bounded, redacted diagnostic detail, when supplied.</summary>
    public string? Detail { get; }

    /// <summary>Gets the redacted actionable hint, when supplied.</summary>
    public string? Hint { get; }

    /// <summary>Gets the original native exception without wrapping, replacement, or redaction.</summary>
    public Exception? NativeInner { get; }

    /// <summary>Creates a credential-safe immutable diagnostic summary.</summary>
    /// <returns>
    /// A summary holding the runtime type's unqualified name, <see cref="Provider"/>,
    /// <see cref="Phase"/>, <see cref="Retryable"/>, <see cref="HttpStatus"/>, and the detail (or the
    /// message when no detail was supplied), redacted again and truncated to 512 Unicode scalar values.
    /// </returns>
    public ErrorInfo Snapshot() => new(GetType().Name, Provider, Phase, Retryable, HttpStatus, Bound(Detail ?? Message));

    /// <summary>Returns a rendered exception description with registered secrets removed.</summary>
    /// <returns>The standard exception rendering, including the stack trace and inner exception chain, with every registered secret spelling replaced by <c>[redacted]</c>.</returns>
    public override string ToString() => Redaction.Redact(base.ToString());

    private static string Sanitize(string value)
    {
        ArgumentNullException.ThrowIfNull(value);
        return Redaction.Redact(value);
    }

    private static string? RedactMetadata(string? value) => value is null ? null : Redaction.Redact(value);

    private static string Bound(string value)
    {
        var redacted = Redaction.Redact(value);
        var runes = redacted.EnumerateRunes().ToArray();
        return runes.Length <= MaximumDetailLength
            ? redacted
            : string.Concat(runes[..(MaximumDetailLength - 1)].Select(static rune => rune.ToString())) + "…";
    }
}

/// <summary>Represents a provider-supplied failure with its original classification metadata.</summary>
/// <remarks>
/// Built-in adapters throw a dedicated subclass when the classified category has one, such as
/// <see cref="RateLimitException"/> for <c>rate_limit</c>. A failure whose category has no dedicated
/// subclass, such as <c>invalid_request</c>, is a plain <see cref="ProviderException"/>, so inspect
/// <see cref="AnyInferException.Category"/> rather than relying only on the runtime type.
/// </remarks>
public class ProviderException : AnyInferException
{
    /// <summary>Initializes a provider failure with classification metadata.</summary>
    /// <remarks>This constructor always creates a <see cref="ProviderException"/>, whatever <paramref name="category"/> says; construct the dedicated subclass when one matches.</remarks>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="category">Stable semantic failure category, such as <c>invalid_request</c>; stored redacted.</param>
    /// <param name="retryable">Whether retrying the failed operation may succeed.</param>
    /// <param name="phase">Lifecycle phase that failed, such as <c>generate</c> or <c>stream</c>; <see langword="null"/> when unknown.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> or <paramref name="category"/> is <see langword="null"/>.</exception>
    public ProviderException(
        string message,
        string category,
        bool retryable,
        string? phase,
        double? retryAfterS = null,
        int? httpStatus = null,
        string? provider = null,
        string? detail = null,
        string? hint = null,
        Exception? nativeInner = null)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner)
    {
    }

    internal static ProviderException Create(
        string message,
        string category,
        bool retryable,
        string? phase,
        double? retryAfterS = null,
        int? httpStatus = null,
        string? provider = null,
        string? detail = null,
        string? hint = null,
        Exception? nativeInner = null) => category switch
        {
            "auth" => new AuthException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "rate_limit" => new RateLimitException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "model_not_found" => new ModelNotFoundException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "context_length" => new ContextLengthException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "transport" or "timeout" => new TransportException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "stream_protocol" => new StreamProtocolException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "provider_unavailable" => new ProviderUnavailableException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            "unsupported_input" => new UnsupportedInputException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
            _ => new ProviderException(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner),
        };
}

/// <summary>Represents an invalid AnyInfer configuration.</summary>
/// <remarks>
/// The category is always <c>config</c>, the phase <c>configure</c>, and the failure is never
/// retryable. Configuration loading failures name their source (the file path, or the
/// <c>source</c> label given to <see cref="Config.AnyInferConfig.Loads"/>) in the message.
/// </remarks>
public sealed class ConfigException : AnyInferException
{
    /// <summary>Initializes a configuration failure.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier the setting belongs to, or <see langword="null"/> when none applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged but not included by <see cref="ToString"/>; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public ConfigException(string message, string? provider = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "config", false, "configure", null, null, provider, detail, hint, nativeInner)
    {
    }

    /// <summary>Returns only the redacted outer configuration failure and never renders a native exception chain.</summary>
    /// <returns>The exception's full type name and redacted message, without a stack trace or inner exceptions.</returns>
    public override string ToString() => $"{GetType().FullName}: {Redaction.Redact(Message)}";
}

/// <summary>Represents an unavailable or invalid credential reference.</summary>
/// <remarks>The category is always <c>credential</c>, the phase <c>configure</c>, and the failure is never retryable.</remarks>
public sealed class CredentialException : AnyInferException
{
    /// <summary>Initializes a credential failure.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier the credential belongs to, or <see langword="null"/> when none applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public CredentialException(string message, string? provider = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "credential", false, "configure", null, null, provider, detail, hint, nativeInner)
    {
    }
}

/// <summary>Represents an authentication failure.</summary>
public sealed class AuthException : ProviderException
{
    /// <summary>Initializes an authentication failure with category <c>auth</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="false"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public AuthException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "auth", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal AuthException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a rate-limit failure.</summary>
public sealed class RateLimitException : ProviderException
{
    /// <summary>Initializes a rate-limit failure with category <c>rate_limit</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="true"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public RateLimitException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "rate_limit", retryable ?? true, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal RateLimitException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents an unknown or unavailable model.</summary>
public sealed class ModelNotFoundException : ProviderException
{
    /// <summary>Initializes a model-not-found failure with category <c>model_not_found</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="false"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public ModelNotFoundException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "model_not_found", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal ModelNotFoundException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents an input that exceeds a provider context limit.</summary>
public sealed class ContextLengthException : ProviderException
{
    /// <summary>Initializes a context-length failure with category <c>context_length</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="false"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public ContextLengthException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "context_length", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal ContextLengthException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a provider transport failure.</summary>
public class TransportException : ProviderException
{
    /// <summary>Initializes a transport failure with category <c>transport</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="true"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public TransportException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "transport", retryable ?? true, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal TransportException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a malformed provider streaming protocol outcome.</summary>
public sealed class StreamProtocolException : ProviderException
{
    /// <summary>Initializes a stream-protocol failure with category <c>stream_protocol</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>stream</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="false"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public StreamProtocolException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "stream_protocol", retryable ?? false, phase ?? "stream", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal StreamProtocolException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a temporarily unavailable provider.</summary>
public sealed class ProviderUnavailableException : ProviderException
{
    /// <summary>Initializes a provider-unavailable failure with category <c>provider_unavailable</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="true"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public ProviderUnavailableException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "provider_unavailable", retryable ?? true, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal ProviderUnavailableException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a request shape the provider does not support.</summary>
public sealed class UnsupportedInputException : ProviderException
{
    /// <summary>Initializes an unsupported-input failure with category <c>unsupported_input</c>.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier, or <see langword="null"/> when unknown.</param>
    /// <param name="phase">Lifecycle phase that failed; <see langword="null"/> selects <c>generate</c>.</param>
    /// <param name="retryable">Whether retrying may succeed; <see langword="null"/> selects <see langword="false"/>.</param>
    /// <param name="retryAfterS">Provider-requested retry delay in seconds, or <see langword="null"/> when none was supplied.</param>
    /// <param name="httpStatus">HTTP status code of the failed response, or <see langword="null"/> when no response status applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public UnsupportedInputException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "unsupported_input", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal UnsupportedInputException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a schema validation failure.</summary>
/// <remarks>The category is always <c>schema_violation</c>, the phase <c>validate</c>, and the failure is never retryable.</remarks>
public sealed class SchemaViolationException : AnyInferException
{
    /// <summary>Initializes a schema validation failure.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="issues">Schema issues that caused the failure; copied in order into <see cref="Issues"/>.</param>
    /// <param name="provider">Provider instance identifier whose output failed validation, or <see langword="null"/> when none applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> or <paramref name="issues"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="issues"/> contains a <see langword="null"/> element.</exception>
    public SchemaViolationException(string message, IEnumerable<Issue> issues, string? provider = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "schema_violation", false, "validate", null, null, provider, detail, hint, nativeInner)
    {
        ArgumentNullException.ThrowIfNull(issues);
        Issues = Array.AsReadOnly(issues.Select(static issue => issue ?? throw new ArgumentException("Issues cannot contain null references.")).ToArray());
    }

    /// <summary>Gets the schema issues that caused this failure.</summary>
    public IReadOnlyList<Issue> Issues { get; }
}

/// <summary>Represents a terminal failure while resolving a schema resource.</summary>
/// <remarks>
/// The category is always <c>schema_reference</c>, the phase <c>validate</c>, and the failure is
/// never retryable. <see cref="AnyInferException.Hint"/> always suggests registering the resource or
/// supplying an explicit schema retriever.
/// </remarks>
public sealed class SchemaReferenceException : AnyInferException
{
    /// <summary>Initializes a schema-resource resolution failure.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="resourceUri">Absolute URI of the unresolved resource; any fragment is removed before it is stored in <see cref="ResourceUri"/>.</param>
    /// <param name="fragment">Unresolved fragment within the resource, stored as given, or <see langword="null"/> when none applies.</param>
    /// <param name="provider">Provider instance identifier associated with the validation, or <see langword="null"/> when none applies.</param>
    /// <param name="nativeInner">Original exception, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> or <paramref name="resourceUri"/> is <see langword="null"/>.</exception>
    public SchemaReferenceException(string message, Uri resourceUri, string? fragment = null, string? provider = null, Exception? nativeInner = null)
        : base(message, "schema_reference", false, "validate", null, null, provider, null, "Register the resource or provide an explicit schema retriever.", nativeInner)
    {
        ResourceUri = new UriBuilder(resourceUri ?? throw new ArgumentNullException(nameof(resourceUri))) { Fragment = string.Empty }.Uri;
        Fragment = fragment;
    }

    /// <summary>Gets the fragment-free resource URI.</summary>
    public Uri ResourceUri { get; }
    /// <summary>Gets the unresolved fragment when supplied.</summary>
    public string? Fragment { get; }
}

/// <summary>Represents a terminal native schema evaluation failure, including regex timeout or unsupported numeric evaluation.</summary>
public sealed class SchemaEvaluationException : AnyInferException
{
    /// <summary>Initializes a terminal native schema-evaluation failure.</summary>
    /// <remarks>The category is always <c>schema_evaluation</c>, the phase <c>validate</c>, the failure is never retryable, and a fixed hint is supplied.</remarks>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="provider">Provider instance identifier associated with the validation, or <see langword="null"/> when none applies.</param>
    /// <param name="nativeInner">Original exception, such as a regular-expression timeout, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public SchemaEvaluationException(string message, string? provider = null, Exception? nativeInner = null)
        : base(message, "schema_evaluation", false, "validate", null, null, provider, null, "Use a simpler schema or a representable numeric range, or increase the configured regex timeout.", nativeInner)
    {
    }
}

/// <summary>Represents an exhausted ordered set of target attempts.</summary>
/// <remarks>
/// The category is always <c>all_targets_failed</c>, the phase <c>generate</c> (also for embedding
/// and rerank routes), and the failure is never retryable as a whole. Each failed attempt keeps its
/// own error in <see cref="Attempts"/>.
/// </remarks>
public sealed class AllTargetsFailedException : AnyInferException
{
    /// <summary>Initializes a failure containing every target attempt.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="attempts">Every attempt made, in order; copied into <see cref="Attempts"/>.</param>
    /// <param name="provider">Provider instance identifier to associate with the overall failure, or <see langword="null"/> when none applies.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, such as the last attempt's failure, preserved unchanged; <see langword="null"/> for none.</param>
    /// <param name="batchFailures">Per-batch outcomes of a batched retrieval request, copied in order into <see cref="BatchFailures"/>; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> or <paramref name="attempts"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="attempts"/> or <paramref name="batchFailures"/> contains a <see langword="null"/> element.</exception>
    public AllTargetsFailedException(
        string message,
        IEnumerable<AttemptRecord> attempts,
        string? provider = null,
        string? detail = null,
        string? hint = null,
        Exception? nativeInner = null,
        IEnumerable<BatchFailure>? batchFailures = null)
        : base(message, "all_targets_failed", false, "generate", null, null, provider, detail, hint, nativeInner)
    {
        ArgumentNullException.ThrowIfNull(attempts);
        Attempts = Array.AsReadOnly(attempts.Select(static attempt => attempt ?? throw new ArgumentException("Attempts cannot contain null references.")).ToArray());
        BatchFailures = Array.AsReadOnly((batchFailures ?? []).Select(static failure => failure ?? throw new ArgumentException("Batch failures cannot contain null references.")).ToArray());
    }

    /// <summary>Gets the ordered failed target attempts.</summary>
    public IReadOnlyList<AttemptRecord> Attempts { get; }

    /// <summary>Gets copied internal batch outcomes for a retrieval failure; empty when the failure was not a batched retrieval.</summary>
    public IReadOnlyList<BatchFailure> BatchFailures { get; }
}

/// <summary>Represents a bounded tool-loop declaration, dispatch, or exhaustion failure.</summary>
/// <remarks>The category is always <c>tool_loop</c>, the phase <c>generate</c>, no provider is recorded, and the failure is never retryable.</remarks>
public sealed class ToolLoopException : AnyInferException
{
    /// <summary>Initializes a nonretryable tool-loop failure.</summary>
    /// <param name="message">Failure message; registered secrets are redacted.</param>
    /// <param name="detail">Diagnostic detail, redacted and truncated to 512 Unicode scalar values; <see langword="null"/> for none.</param>
    /// <param name="hint">Actionable next step for the caller, redacted; <see langword="null"/> for none.</param>
    /// <param name="nativeInner">Original exception, such as one thrown by a tool handler, preserved unchanged; <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="message"/> is <see langword="null"/>.</exception>
    public ToolLoopException(string message, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "tool_loop", false, "generate", null, null, null, detail, hint, nativeInner)
    {
    }
}
