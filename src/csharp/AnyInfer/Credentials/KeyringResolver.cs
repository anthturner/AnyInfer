namespace AnyInfer.Credentials;

/// <summary>Recognizes keyring references and reports that platform keyring support is unavailable.</summary>
/// <remarks>
/// This build has no operating-system keyring integration. The resolver claims
/// <c>credential://</c> references so that configuration loading accepts them and the literal
/// resolver never sends one as a credential, but every resolution fails with a
/// <see cref="CredentialException"/> when the provider instance is created. Use an <c>env://</c>
/// reference, a literal value, or a custom <see cref="ICredentialResolver"/> instead.
/// </remarks>
public sealed class KeyringResolver : ICredentialResolver
{
    /// <summary>Creates a keyring-reference resolver; the instance holds no state.</summary>
    public KeyringResolver()
    {
    }

    /// <summary>Determines whether the reference uses the <c>credential://</c> scheme.</summary>
    /// <param name="reference">Candidate credential reference; <see langword="null"/> is not handled.</param>
    /// <returns><see langword="true"/> when <paramref name="reference"/> starts with the case-sensitive prefix <c>credential://</c>; otherwise <see langword="false"/>.</returns>
    public bool Handles(string reference) => reference?.StartsWith("credential://", StringComparison.Ordinal) == true;

    /// <summary>Fails with an actionable error because this build has no platform keyring integration.</summary>
    /// <param name="reference">A <c>credential://</c> reference.</param>
    /// <param name="cancellationToken">Checked once before the call fails.</param>
    /// <returns>Never returns a value; every call throws.</returns>
    /// <exception cref="CredentialException">Always: keyring credentials are unavailable, or <paramref name="reference"/> is not a <c>credential://</c> reference.</exception>
    /// <exception cref="OperationCanceledException"><paramref name="cancellationToken"/> is already canceled.</exception>
    public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!Handles(reference))
        {
            throw new CredentialException("The keyring resolver cannot handle this credential reference.");
        }

        throw new CredentialException("Platform keyring credentials are unavailable in this build.", hint: "Use env://, a literal credential, or a custom credential resolver.");
    }
}
