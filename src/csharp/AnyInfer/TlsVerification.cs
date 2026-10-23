namespace AnyInfer;

/// <summary>Immutable per-instance TLS verification settings for SDK-created HTTP handlers.</summary>
public sealed record TlsVerification
{
    private TlsVerification(string? pemBundlePath)
    {
        PemBundlePath = pemBundlePath;
    }

    /// <summary>Gets the explicit per-handler setting that disables certificate verification.</summary>
    public static TlsVerification Disabled { get; } = new(pemBundlePath: null);

    /// <summary>Gets the optional configured PEM CA-bundle file path.</summary>
    public string? PemBundlePath { get; }

    /// <summary>Creates verification settings for a PEM CA-bundle file without accessing the path.</summary>
    public static TlsVerification FromPemBundle(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("The PEM CA-bundle path cannot be blank.", nameof(path));
        }

        return new TlsVerification(path.Trim());
    }

    /// <summary>Returns an identity-only representation that omits the configured path.</summary>
    public override string ToString() => PemBundlePath is null ? "TlsVerification.Disabled" : "TlsVerification.PemBundle";
}
