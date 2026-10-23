namespace AnyInfer;

/// <summary>Immutable PEM client-certificate settings for one SDK-created HTTP handler.</summary>
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

    /// <summary>Gets the optional private-key PEM path.</summary>
    public string? PrivateKeyPath { get; }

    /// <summary>Gets the optional encrypted private-key password; do not log this value.</summary>
    public string? Password { get; }

    /// <summary>Creates settings for one combined unencrypted PEM certificate and key file.</summary>
    public static ClientCertificate FromPemFile(string certificatePath) =>
        new(RequiredPath(certificatePath, nameof(certificatePath)), null, null);

    /// <summary>Creates settings for separate unencrypted certificate and private-key PEM files.</summary>
    public static ClientCertificate FromPemPair(string certificatePath, string privateKeyPath) =>
        new(RequiredPath(certificatePath, nameof(certificatePath)), RequiredPath(privateKeyPath, nameof(privateKeyPath)), null);

    /// <summary>Creates settings for separate encrypted certificate and private-key PEM files.</summary>
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
