namespace AnyInfer;

/// <summary>Describes advisory provider runtime information without failing a request.</summary>
public sealed record Diagnostic
{
    /// <summary>Initializes an immutable advisory diagnostic.</summary>
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
