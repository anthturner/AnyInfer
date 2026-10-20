using AnyInfer.Schema;
using System.Text;

namespace AnyInfer;

/// <summary>Contains a safe, serializable summary of an AnyInfer exception.</summary>
public sealed record ErrorInfo(
    string TypeName,
    string? Provider,
    string? Phase,
    bool Retryable,
    int? HttpStatus,
    string? Detail);

/// <summary>Base exception for typed AnyInfer failures with provider and retry metadata.</summary>
public class AnyInferException : Exception
{
    private const int MaximumDetailLength = 512;

    /// <summary>Initializes an AnyInfer exception while preserving the original native exception.</summary>
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

    /// <summary>Gets the stable semantic failure category.</summary>
    public string Category { get; }

    /// <summary>Gets whether the failed operation may be retried.</summary>
    public bool Retryable { get; }

    /// <summary>Gets the lifecycle phase that failed, when known.</summary>
    public string? Phase { get; }

    /// <summary>Gets the server supplied retry delay in seconds, when known.</summary>
    public double? RetryAfterS { get; }

    /// <summary>Gets the protocol HTTP status, when known.</summary>
    public int? HttpStatus { get; }

    /// <summary>Gets the provider identifier associated with the failure, when known.</summary>
    public string? Provider { get; }

    /// <summary>Gets the bounded, redacted diagnostic detail, when supplied.</summary>
    public string? Detail { get; }

    /// <summary>Gets the redacted actionable hint, when supplied.</summary>
    public string? Hint { get; }

    /// <summary>Gets the original native exception without wrapping or replacement.</summary>
    public Exception? NativeInner { get; }

    /// <summary>Creates a credential-safe immutable diagnostic summary.</summary>
    public ErrorInfo Snapshot() => new(GetType().Name, Provider, Phase, Retryable, HttpStatus, Bound(Detail ?? Message));

    /// <summary>Returns a rendered exception chain with registered secrets removed.</summary>
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
public class ProviderException : AnyInferException
{
    /// <summary>Initializes a provider failure with classification metadata.</summary>
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
public sealed class ConfigException : AnyInferException
{
    /// <summary>Initializes a configuration failure.</summary>
    public ConfigException(string message, string? provider = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "config", false, "configure", null, null, provider, detail, hint, nativeInner)
    {
    }
}

/// <summary>Represents an unavailable or invalid credential reference.</summary>
public sealed class CredentialException : AnyInferException
{
    /// <summary>Initializes a credential failure.</summary>
    public CredentialException(string message, string? provider = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "credential", false, "configure", null, null, provider, detail, hint, nativeInner)
    {
    }
}

/// <summary>Represents an authentication failure.</summary>
public sealed class AuthException : ProviderException
{
    /// <summary>Initializes an authentication failure.</summary>
    public AuthException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "auth", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal AuthException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a rate-limit failure.</summary>
public sealed class RateLimitException : ProviderException
{
    /// <summary>Initializes a rate-limit failure.</summary>
    public RateLimitException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "rate_limit", retryable ?? true, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal RateLimitException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents an unknown or unavailable model.</summary>
public sealed class ModelNotFoundException : ProviderException
{
    /// <summary>Initializes a model-not-found failure.</summary>
    public ModelNotFoundException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "model_not_found", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal ModelNotFoundException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents an input that exceeds a provider context limit.</summary>
public sealed class ContextLengthException : ProviderException
{
    /// <summary>Initializes a context-length failure.</summary>
    public ContextLengthException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "context_length", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal ContextLengthException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a provider transport failure.</summary>
public class TransportException : ProviderException
{
    /// <summary>Initializes a transport failure.</summary>
    public TransportException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "transport", retryable ?? true, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal TransportException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a malformed provider streaming protocol outcome.</summary>
public sealed class StreamProtocolException : ProviderException
{
    /// <summary>Initializes a stream-protocol failure.</summary>
    public StreamProtocolException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "stream_protocol", retryable ?? false, phase ?? "stream", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal StreamProtocolException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a temporarily unavailable provider.</summary>
public sealed class ProviderUnavailableException : ProviderException
{
    /// <summary>Initializes a provider-unavailable failure.</summary>
    public ProviderUnavailableException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "provider_unavailable", retryable ?? true, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal ProviderUnavailableException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a request shape the provider does not support.</summary>
public sealed class UnsupportedInputException : ProviderException
{
    /// <summary>Initializes an unsupported-input failure.</summary>
    public UnsupportedInputException(string message, string? provider = null, string? phase = null, bool? retryable = null, double? retryAfterS = null, int? httpStatus = null, string? detail = null, string? hint = null, Exception? nativeInner = null)
        : base(message, "unsupported_input", retryable ?? false, phase ?? "generate", retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }

    internal UnsupportedInputException(string message, string category, bool retryable, string? phase, double? retryAfterS, int? httpStatus, string? provider, string? detail, string? hint, Exception? nativeInner)
        : base(message, category, retryable, phase, retryAfterS, httpStatus, provider, detail, hint, nativeInner) { }
}

/// <summary>Represents a schema validation failure.</summary>
public sealed class SchemaViolationException : AnyInferException
{
    /// <summary>Initializes a schema validation failure.</summary>
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
public sealed class SchemaReferenceException : AnyInferException
{
    /// <summary>Initializes a schema-resource resolution failure.</summary>
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
    public SchemaEvaluationException(string message, string? provider = null, Exception? nativeInner = null)
        : base(message, "schema_evaluation", false, "validate", null, null, provider, null, "Use a simpler schema or a representable numeric range, or increase the configured regex timeout.", nativeInner)
    {
    }
}

/// <summary>Represents an exhausted ordered set of target attempts.</summary>
public sealed class AllTargetsFailedException : AnyInferException
{
    /// <summary>Initializes a failure containing every target attempt.</summary>
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

    /// <summary>Gets copied internal batch outcomes for a retrieval failure.</summary>
    public IReadOnlyList<BatchFailure> BatchFailures { get; }
}
