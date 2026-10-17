namespace AnyInfer.Credentials;

/// <summary>Resolves credential references through an ordered, thread-safe set of resolvers.</summary>
public sealed class ResolverChain
{
    private readonly object _gate = new();
    private readonly List<ICredentialResolver> _resolvers;

    /// <summary>Creates an ordered resolver chain.</summary>
    public ResolverChain(IEnumerable<ICredentialResolver> resolvers)
    {
        ArgumentNullException.ThrowIfNull(resolvers);
        _resolvers = resolvers.Select(static resolver => resolver ?? throw new ArgumentException("Resolvers cannot contain null references.")).ToList();
    }

    /// <summary>Creates the built-in keyring, environment, and literal resolver chain.</summary>
    public static ResolverChain CreateDefault() => new([new KeyringResolver(), new EnvResolver(), new LiteralResolver()]);

    /// <summary>Adds a resolver before or after the existing ordered resolvers.</summary>
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
    public bool Handles(string reference)
    {
        ArgumentNullException.ThrowIfNull(reference);
        return Snapshot().Any(resolver => resolver.Handles(reference));
    }

    /// <summary>Resolves a nonblank reference and registers the returned secret for redaction.</summary>
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
