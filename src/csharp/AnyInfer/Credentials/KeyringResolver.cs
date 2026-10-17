namespace AnyInfer.Credentials;

/// <summary>Recognizes keyring references and reports that platform keyring support is unavailable.</summary>
public sealed class KeyringResolver : ICredentialResolver
{
    /// <summary>Determines whether the reference uses the <c>credential://</c> scheme.</summary>
    public bool Handles(string reference) => reference?.StartsWith("credential://", StringComparison.Ordinal) == true;

    /// <summary>Fails with an actionable error because this proof build has no platform keyring integration.</summary>
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
