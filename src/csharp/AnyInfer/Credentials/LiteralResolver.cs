namespace AnyInfer.Credentials;

/// <summary>Resolves a literal credential value while refusing URI-shaped references.</summary>
/// <remarks>
/// A value is treated as a reference, and refused, when it starts with <c>env:</c> or
/// <c>credential:</c>, or has the shape <c>scheme://</c> with a scheme of an ASCII letter followed by
/// ASCII letters, digits, <c>+</c>, <c>-</c>, or <c>.</c>. Such a value needs a resolver for its
/// scheme, so a mistyped or unsupported reference is never sent as the credential itself.
/// </remarks>
public sealed class LiteralResolver : ICredentialResolver
{
    /// <summary>Creates a literal-value resolver; the instance holds no state.</summary>
    public LiteralResolver()
    {
    }

    /// <summary>Determines whether the value is a nonblank literal rather than a credential URI.</summary>
    /// <param name="reference">Candidate literal credential value.</param>
    /// <returns><see langword="true"/> when <paramref name="reference"/> is not <see langword="null"/>, empty, or whitespace and is not reference-shaped; otherwise <see langword="false"/>.</returns>
    public bool Handles(string reference) => !string.IsNullOrWhiteSpace(reference) && !LooksLikeReference(reference);

    /// <summary>Returns a literal credential value without external I/O.</summary>
    /// <param name="reference">The literal credential value.</param>
    /// <param name="cancellationToken">Checked once before the value is returned.</param>
    /// <returns><paramref name="reference"/> unchanged. The operation completes synchronously.</returns>
    /// <exception cref="CredentialException"><paramref name="reference"/> is blank or reference-shaped.</exception>
    /// <exception cref="OperationCanceledException"><paramref name="cancellationToken"/> is already canceled.</exception>
    public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!Handles(reference))
        {
            throw new CredentialException("The literal resolver cannot handle a credential reference URI.");
        }

        return ValueTask.FromResult(reference);
    }

    private static bool LooksLikeReference(string value)
    {
        if (value.StartsWith("env:", StringComparison.Ordinal) || value.StartsWith("credential:", StringComparison.Ordinal))
        {
            return true;
        }

        var separator = value.IndexOf("://", StringComparison.Ordinal);
        return separator > 0 && IsAsciiLetter(value[0]) && value[..separator].All(static character => IsAsciiLetter(character) || IsAsciiDigit(character) || character is '+' or '-' or '.');
    }

    private static bool IsAsciiLetter(char value) => value is >= 'A' and <= 'Z' or >= 'a' and <= 'z';

    private static bool IsAsciiDigit(char value) => value is >= '0' and <= '9';
}
