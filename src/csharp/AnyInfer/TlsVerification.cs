namespace AnyInfer;

/// <summary>Immutable per-instance TLS verification settings for SDK-created HTTP handlers.</summary>
/// <remarks>
/// Leaving <see cref="ProviderSettings.Verify"/> unset keeps platform certificate verification. These
/// settings apply only to the handler AnyInfer creates for the instance; a handler supplied through
/// <see cref="ProviderSettings.Transport"/> bypasses them. <see cref="ToString"/> omits the path, but
/// <see cref="Config.AnyInferConfig.Dumps"/> writes it.
/// </remarks>
public sealed record TlsVerification
{
    private TlsVerification(string? pemBundlePath)
    {
        PemBundlePath = pemBundlePath;
    }

    /// <summary>Gets the explicit per-handler setting that disables certificate verification.</summary>
    /// <remarks>The SDK-created handler then accepts any server certificate, so the connection can be intercepted by anything on the network path. Prefer <see cref="FromPemBundle"/> for a private or intercepting certificate authority.</remarks>
    public static TlsVerification Disabled { get; } = new(pemBundlePath: null);

    /// <summary>Gets the optional configured PEM CA-bundle file path; <see langword="null"/> for <see cref="Disabled"/>.</summary>
    public string? PemBundlePath { get; }

    /// <summary>Creates verification settings for a PEM CA-bundle file without accessing the path.</summary>
    /// <remarks>
    /// The file is read when the provider first creates its HTTP handler. Server certificates are then
    /// validated against the bundle's certificates as the only trust roots, without revocation checks
    /// or certificate downloads. A directory of CA files is not supported, and a missing, unreadable,
    /// or certificate-free file fails with a <see cref="ConfigException"/> at that point.
    /// </remarks>
    /// <param name="path">Path of a PEM file containing one or more CA certificates; surrounding whitespace is removed.</param>
    /// <returns>Settings that select the bundle's certificates as custom trust roots.</returns>
    /// <exception cref="ArgumentException"><paramref name="path"/> is <see langword="null"/>, empty, or whitespace.</exception>
    public static TlsVerification FromPemBundle(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("The PEM CA-bundle path cannot be blank.", nameof(path));
        }

        return new TlsVerification(path.Trim());
    }

    /// <summary>Returns an identity-only representation that omits the configured path.</summary>
    /// <returns><c>TlsVerification.Disabled</c> or <c>TlsVerification.PemBundle</c>.</returns>
    public override string ToString() => PemBundlePath is null ? "TlsVerification.Disabled" : "TlsVerification.PemBundle";
}
