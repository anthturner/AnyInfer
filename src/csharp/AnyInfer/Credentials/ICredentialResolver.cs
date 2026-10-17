namespace AnyInfer.Credentials;

/// <summary>Resolves one supported credential reference without performing work during admission.</summary>
public interface ICredentialResolver
{
    /// <summary>Determines whether this resolver can resolve the supplied reference without I/O.</summary>
    bool Handles(string reference);

    /// <summary>Resolves a credential value for a supported reference.</summary>
    ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default);
}
