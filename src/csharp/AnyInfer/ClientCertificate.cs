namespace AnyInfer;

/// <summary>Immutable PEM client-certificate settings for one SDK-created HTTP handler.</summary>
/// <remarks>
/// The factories store paths without accessing them. The certificate and key are loaded when the
/// provider first creates its HTTP handler, and a missing or unparsable file, or a wrong password,
/// fails with a <see cref="ConfigException"/> at that point. A handler supplied through
/// <see cref="ProviderSettings.Transport"/> bypasses these settings. The password is registered for
/// redaction when the handler is created. <see cref="ToString"/> omits paths and the password, but
/// <see cref="Config.AnyInferConfig.Dumps"/> writes both, so protect that output.
/// </remarks>
public sealed record ClientCertificate
{
    private ClientCertificate(string certificatePath, string? privateKeyPath, string? password)
    {
        CertificatePath = certificatePath;
        PrivateKeyPath = privateKeyPath;
        Password = password;
    }

    /// <summary>Gets the combined or leaf-certificate PEM path.</summary>
    public string CertificatePath { get; }

    /// <summary>Gets the optional private-key PEM path; <see langword="null"/> when the key is in <see cref="CertificatePath"/>.</summary>
    public string? PrivateKeyPath { get; }

    /// <summary>Gets the optional encrypted private-key password; do not log this value.</summary>
    public string? Password { get; }

    /// <summary>Creates settings for one combined unencrypted PEM certificate and key file.</summary>
    /// <param name="certificatePath">Path of a PEM file holding the client certificate and its unencrypted private key.</param>
    /// <returns>Settings for the combined file.</returns>
    /// <exception cref="ArgumentException"><paramref name="certificatePath"/> is <see langword="null"/> or empty.</exception>
    public static ClientCertificate FromPemFile(string certificatePath) =>
        new(RequiredPath(certificatePath, nameof(certificatePath)), null, null);

    /// <summary>Creates settings for separate unencrypted certificate and private-key PEM files.</summary>
    /// <param name="certificatePath">Path of the client-certificate PEM file.</param>
    /// <param name="privateKeyPath">Path of the unencrypted private-key PEM file.</param>
    /// <returns>Settings for the certificate and key pair.</returns>
    /// <exception cref="ArgumentException"><paramref name="certificatePath"/> or <paramref name="privateKeyPath"/> is <see langword="null"/> or empty.</exception>
    public static ClientCertificate FromPemPair(string certificatePath, string privateKeyPath) =>
        new(RequiredPath(certificatePath, nameof(certificatePath)), RequiredPath(privateKeyPath, nameof(privateKeyPath)), null);

    /// <summary>Creates settings for separate encrypted certificate and private-key PEM files.</summary>
    /// <param name="certificatePath">Path of the client-certificate PEM file.</param>
    /// <param name="privateKeyPath">Path of the encrypted private-key PEM file; it may be the same path as <paramref name="certificatePath"/> for a combined file.</param>
    /// <param name="password">Literal password that decrypts the private key; do not log it.</param>
    /// <returns>Settings for the certificate and encrypted key.</returns>
    /// <exception cref="ArgumentException">A path or <paramref name="password"/> is <see langword="null"/> or empty.</exception>
    public static ClientCertificate FromEncryptedPemPair(string certificatePath, string privateKeyPath, string password)
    {
        if (string.IsNullOrEmpty(password))
        {
            throw new ArgumentException("The PEM private-key password cannot be blank.", nameof(password));
        }

        return new(
            RequiredPath(certificatePath, nameof(certificatePath)),
            RequiredPath(privateKeyPath, nameof(privateKeyPath)),
            password);
    }

    /// <summary>Returns an identity-only representation that omits paths and the password.</summary>
    /// <returns><c>ClientCertificate.PemFile</c>, <c>ClientCertificate.PemPair</c>, or <c>ClientCertificate.EncryptedPemPair</c>.</returns>
    public override string ToString() => Password is not null
        ? "ClientCertificate.EncryptedPemPair"
        : PrivateKeyPath is null ? "ClientCertificate.PemFile" : "ClientCertificate.PemPair";

    private static string RequiredPath(string value, string parameterName)
    {
        if (string.IsNullOrEmpty(value))
        {
            throw new ArgumentException("The PEM path cannot be blank.", parameterName);
        }

        return value;
    }
}
