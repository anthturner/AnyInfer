using AnyInfer.Config;
using AnyInfer.Credentials;

namespace AnyInfer.Examples;

/// <summary>
/// Loads configuration whose API keys are credential references, and resolves an application-owned
/// reference scheme with a custom resolver.
/// </summary>
public static class CredentialReferenceExample
{
    // --8<-- [start:load]
    /// <summary>Loads version 1 configuration text without resolving any credential reference.</summary>
    /// <param name="json">The configuration document.</param>
    /// <param name="resolver">
    /// The resolver chain that must accept each <c>api_key</c>, or <see langword="null"/> for the default
    /// chain. Pass the same chain to the client that will resolve the references.
    /// </param>
    /// <returns>The validated, inert configuration.</returns>
    public static AnyInferConfig Load(string json, ResolverChain? resolver = null) =>
        AnyInferConfig.Loads(json, resolver: resolver);

    /// <summary>Sends one prompt through the configured default route.</summary>
    /// <param name="config">Configuration from <see cref="Load"/>.</param>
    /// <param name="prompt">The prompt text.</param>
    /// <param name="resolver">The resolver chain used when the configuration was loaded.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The buffered result.</returns>
    public static async Task<Generation> AskAsync(
        AnyInferConfig config,
        string prompt,
        ResolverChain? resolver = null,
        CancellationToken cancellationToken = default)
    {
        // Neither loading nor client construction resolves a reference; the first call that needs the
        // provider instance does, before its request is sent.
        await using var client = AsyncClient.FromConfig(config, resolver: resolver);
        return await client.GenerateAsync(prompt, cancellationToken: cancellationToken);
    }
    // --8<-- [end:load]

    // --8<-- [start:resolver]
    /// <summary>Creates the default resolver chain with an application secret store in front of it.</summary>
    /// <param name="secrets">Secrets the application already holds, keyed by name.</param>
    /// <returns>A chain that also resolves <c>app-secret://NAME</c> references.</returns>
    public static ResolverChain WithApplicationSecrets(IReadOnlyDictionary<string, string> secrets)
    {
        var chain = ResolverChain.CreateDefault();
        chain.Add(new ApplicationSecretResolver(secrets));
        return chain;
    }

    /// <summary>Resolves <c>app-secret://NAME</c> references from an application-owned secret store.</summary>
    /// <param name="secrets">Secrets keyed by name.</param>
    public sealed class ApplicationSecretResolver(IReadOnlyDictionary<string, string> secrets) : ICredentialResolver
    {
        private const string Scheme = "app-secret://";

        /// <inheritdoc />
        public bool Handles(string reference) => reference?.StartsWith(Scheme, StringComparison.Ordinal) == true;

        /// <inheritdoc />
        public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return secrets.TryGetValue(reference[Scheme.Length..], out var secret)
                ? ValueTask.FromResult(secret)
                : throw new CredentialException("The application secret is unavailable.");
        }
    }
    // --8<-- [end:resolver]
}
