namespace AnyInfer.Credentials;

/// <summary>Resolves credential references from process environment variables.</summary>
/// <remarks>
/// A reference has the form <c>env://NAME</c>. The variable is read from the current process
/// environment each time <see cref="ResolveAsync"/> is called, so a change made after configuration
/// loading is seen by the next resolution. Calling this resolver directly does not register the value
/// for redaction; <see cref="ResolverChain.ResolveAsync"/> does.
/// </remarks>
public sealed class EnvResolver : ICredentialResolver
{
    /// <summary>Creates an environment-variable resolver; the instance holds no state.</summary>
    public EnvResolver()
    {
    }

    /// <summary>Determines whether the reference uses the <c>env://</c> scheme.</summary>
    /// <param name="reference">Candidate credential reference; <see langword="null"/> is not handled.</param>
    /// <returns><see langword="true"/> when <paramref name="reference"/> starts with the case-sensitive prefix <c>env://</c>; otherwise <see langword="false"/>.</returns>
    public bool Handles(string reference) => reference?.StartsWith("env://", StringComparison.Ordinal) == true;

    /// <summary>Resolves a nonempty environment variable named by an <c>env://</c> reference.</summary>
    /// <param name="reference">An <c>env://NAME</c> reference; the text after the prefix is trimmed and used as the variable name.</param>
    /// <param name="cancellationToken">Checked once before the variable is read.</param>
    /// <returns>The variable's value, unchanged. The operation completes synchronously.</returns>
    /// <exception cref="CredentialException"><paramref name="reference"/> is not an <c>env://</c> reference, names no variable, or names a variable that is unset or empty.</exception>
    /// <exception cref="OperationCanceledException"><paramref name="cancellationToken"/> is already canceled.</exception>
    public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!Handles(reference))
        {
            throw new CredentialException("The environment resolver cannot handle this credential reference.");
        }

        var name = reference["env://".Length..].Trim();
        var value = string.IsNullOrWhiteSpace(name) ? null : Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrEmpty(value))
        {
            throw new CredentialException("The requested environment credential is unavailable.", hint: "Set the referenced environment variable before dispatch.");
        }

        return ValueTask.FromResult(value);
    }
}
