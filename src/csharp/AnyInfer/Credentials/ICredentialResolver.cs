namespace AnyInfer.Credentials;

/// <summary>Resolves one supported credential reference without performing work during admission.</summary>
/// <remarks>
/// <see cref="Handles"/> is the admission check: configuration loading and
/// <see cref="ResolverChain.Handles"/> call it to accept a value without resolving it, so it should be
/// a pure, fast test that performs no I/O and does not throw for values it does not recognize.
/// <see cref="ResolveAsync"/> runs later, when a provider instance that uses the credential is
/// created. Add an implementation to a chain with <see cref="ResolverChain.Add"/> to support a new
/// reference scheme.
/// </remarks>
public interface ICredentialResolver
{
    /// <summary>Determines whether this resolver can resolve the supplied reference without I/O.</summary>
    /// <param name="reference">Candidate credential reference or literal value.</param>
    /// <returns><see langword="true"/> when this resolver claims <paramref name="reference"/>; otherwise <see langword="false"/>.</returns>
    bool Handles(string reference);

    /// <summary>Resolves a credential value for a supported reference.</summary>
    /// <param name="reference">A reference for which <see cref="Handles"/> returned <see langword="true"/>; <see cref="ResolverChain"/> passes it trimmed.</param>
    /// <param name="cancellationToken">Cancels the resolution.</param>
    /// <returns>The resolved credential value. <see cref="ResolverChain"/> rejects an empty value with a <see cref="CredentialException"/> and registers a nonempty one for redaction.</returns>
    ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default);
}
