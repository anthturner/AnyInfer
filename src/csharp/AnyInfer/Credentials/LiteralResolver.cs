namespace AnyInfer.Credentials;

/// <summary>Resolves a literal credential value while refusing URI-shaped references.</summary>
public sealed class LiteralResolver : ICredentialResolver
{
    /// <summary>Determines whether the value is a nonblank literal rather than a credential URI.</summary>
    public bool Handles(string reference) => !string.IsNullOrWhiteSpace(reference) && !LooksLikeReference(reference);

    /// <summary>Returns a literal credential value without external I/O.</summary>
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
