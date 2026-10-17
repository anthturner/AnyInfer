namespace AnyInfer.Credentials;

/// <summary>Resolves credential references from process environment variables.</summary>
public sealed class EnvResolver : ICredentialResolver
{
    /// <summary>Determines whether the reference uses the <c>env://</c> scheme.</summary>
    public bool Handles(string reference) => reference?.StartsWith("env://", StringComparison.Ordinal) == true;

    /// <summary>Resolves a nonempty environment variable named by an <c>env://</c> reference.</summary>
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
