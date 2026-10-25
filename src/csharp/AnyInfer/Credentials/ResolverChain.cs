namespace AnyInfer.Credentials;

/// <summary>Resolves credential references through an ordered, thread-safe set of resolvers.</summary>
/// <remarks>
/// The first resolver whose <see cref="ICredentialResolver.Handles"/> accepts a reference resolves
/// it; a failure from that resolver is not retried with later resolvers. Every lookup works on a
/// snapshot of the list, so <see cref="Add"/> may run concurrently with resolutions already in
/// progress. Credentials resolved here, including literal values, are registered with
/// <see cref="Redaction"/> before they are returned.
/// </remarks>
public sealed class ResolverChain
{
    private readonly object _gate = new();
    private readonly List<ICredentialResolver> _resolvers;

    /// <summary>Creates an ordered resolver chain.</summary>
    /// <param name="resolvers">Resolvers in priority order, earliest first; the sequence is copied.</param>
    /// <exception cref="ArgumentNullException"><paramref name="resolvers"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="resolvers"/> contains a <see langword="null"/> element.</exception>
    public ResolverChain(IEnumerable<ICredentialResolver> resolvers)
    {
        ArgumentNullException.ThrowIfNull(resolvers);
        _resolvers = resolvers.Select(static resolver => resolver ?? throw new ArgumentException("Resolvers cannot contain null references.")).ToList();
    }

    /// <summary>Creates the built-in keyring, environment, and literal resolver chain.</summary>
    /// <returns>
    /// A new, independent chain of <see cref="KeyringResolver"/> (<c>credential://</c>, which always
    /// fails to resolve in this build), <see cref="EnvResolver"/> (<c>env://</c>), and
    /// <see cref="LiteralResolver"/> (any other non-reference value), in that order.
    /// </returns>
    public static ResolverChain CreateDefault() => new([new KeyringResolver(), new EnvResolver(), new LiteralResolver()]);

    /// <summary>Adds a resolver before or after the existing ordered resolvers.</summary>
    /// <param name="resolver">Resolver to add.</param>
    /// <param name="first"><see langword="true"/> (the default) to give it priority over every existing resolver; <see langword="false"/> to try it last.</param>
    /// <exception cref="ArgumentNullException"><paramref name="resolver"/> is <see langword="null"/>.</exception>
    public void Add(ICredentialResolver resolver, bool first = true)
    {
        ArgumentNullException.ThrowIfNull(resolver);
        lock (_gate)
        {
            if (first)
            {
                _resolvers.Insert(0, resolver);
            }
            else
            {
                _resolvers.Add(resolver);
            }
        }
    }

    /// <summary>Determines whether any resolver can admit the reference without resolving it.</summary>
    /// <param name="reference">Credential reference or literal value, tested as given.</param>
    /// <returns><see langword="true"/> when at least one resolver handles <paramref name="reference"/>; otherwise <see langword="false"/>.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="reference"/> is <see langword="null"/>.</exception>
    public bool Handles(string reference)
    {
        ArgumentNullException.ThrowIfNull(reference);
        return Snapshot().Any(resolver => resolver.Handles(reference));
    }

    /// <summary>Resolves a nonblank reference and registers the returned secret for redaction.</summary>
    /// <param name="reference">Credential reference or literal value; it is trimmed before matching. <see langword="null"/>, empty, or whitespace means no credential is configured.</param>
    /// <param name="cancellationToken">Checked before each resolver is tried and passed to the resolver that handles the reference.</param>
    /// <returns>The resolved credential, already registered with <see cref="Redaction.RegisterSecret(string)"/>; <see langword="null"/> when <paramref name="reference"/> is blank.</returns>
    /// <exception cref="CredentialException">No resolver handles the reference, the handling resolver returns an empty value, or the handling resolver fails with its own credential error.</exception>
    /// <exception cref="OperationCanceledException"><paramref name="cancellationToken"/> is canceled.</exception>
    public async ValueTask<string?> ResolveAsync(string? reference, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(reference))
        {
            return null;
        }

        var normalized = reference.Trim();
        foreach (var resolver in Snapshot())
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!resolver.Handles(normalized))
            {
                continue;
            }

            var secret = await resolver.ResolveAsync(normalized, cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrEmpty(secret))
            {
                throw new CredentialException("Credential resolution returned an empty value.");
            }

            Redaction.RegisterSecret(secret);
            return secret;
        }

        throw new CredentialException("No configured credential resolver handles the supplied reference.", hint: "Configure a resolver for the credential reference scheme.");
    }

    private ICredentialResolver[] Snapshot()
    {
        lock (_gate)
        {
            return _resolvers.ToArray();
        }
    }
}
