using AnyInfer.Schema;

namespace AnyInfer;

public class AnyInferException : Exception
{
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
        : base(message, nativeInner)
    {
        Category = category ?? throw new ArgumentNullException(nameof(category));
        Retryable = retryable;
        Phase = phase;
        RetryAfterS = retryAfterS;
        HttpStatus = httpStatus;
        Provider = provider;
        Detail = detail;
        Hint = hint;
        NativeInner = nativeInner;
    }

    public string Category { get; }
    public bool Retryable { get; }
    public string? Phase { get; }
    public double? RetryAfterS { get; }
    public int? HttpStatus { get; }
    public string? Provider { get; }
    public string? Detail { get; }
    public string? Hint { get; }
    public Exception? NativeInner { get; }
}

public sealed class ProviderException : AnyInferException
{
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
}

public sealed class SchemaViolationException : AnyInferException
{
    public SchemaViolationException(
        string message,
        IEnumerable<Issue> issues,
        string? provider = null,
        string? detail = null,
        string? hint = null,
        Exception? nativeInner = null)
        : base(message, "schema_violation", false, "validate", null, null, provider, detail, hint, nativeInner)
    {
        ArgumentNullException.ThrowIfNull(issues);
        Issues = Array.AsReadOnly(issues.Select(static issue => issue ?? throw new ArgumentException("Issues cannot contain null references.")).ToArray());
    }

    public IReadOnlyList<Issue> Issues { get; }
}

public sealed class AllTargetsFailedException : AnyInferException
{
    public AllTargetsFailedException(
        string message,
        IEnumerable<AttemptRecord> attempts,
        string? provider = null,
        string? detail = null,
        string? hint = null,
        Exception? nativeInner = null)
        : base(message, "all_targets_failed", false, "generate", null, null, provider, detail, hint, nativeInner)
    {
        ArgumentNullException.ThrowIfNull(attempts);
        Attempts = Array.AsReadOnly(attempts.Select(static attempt => attempt ?? throw new ArgumentException("Attempts cannot contain null references.")).ToArray());
    }

    public IReadOnlyList<AttemptRecord> Attempts { get; }
}
