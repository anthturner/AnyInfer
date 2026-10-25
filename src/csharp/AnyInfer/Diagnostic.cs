namespace AnyInfer;

/// <summary>Describes advisory provider runtime information without failing a request.</summary>
/// <remarks>Delivered to observers inside a <see cref="Events.ProviderDiagnostic"/> telemetry event.</remarks>
public sealed record Diagnostic
{
    /// <summary>Initializes an immutable advisory diagnostic.</summary>
    /// <param name="code">The diagnostic code, such as <c>cache.prefix-unstable</c>.</param>
    /// <param name="severity">The severity label, such as <c>info</c>.</param>
    /// <param name="message">A human-readable explanation.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="code"/>, <paramref name="severity"/>, or <paramref name="message"/> is <see langword="null"/>.
    /// </exception>
    public Diagnostic(string code, string severity, string message)
    {
        Code = code ?? throw new ArgumentNullException(nameof(code));
        Severity = severity ?? throw new ArgumentNullException(nameof(severity));
        Message = message ?? throw new ArgumentNullException(nameof(message));
    }

    /// <summary>Gets the provider-defined diagnostic code.</summary>
    public string Code { get; }

    /// <summary>Gets the provider-defined severity.</summary>
    public string Severity { get; }

    /// <summary>Gets the diagnostic message.</summary>
    public string Message { get; }
}
