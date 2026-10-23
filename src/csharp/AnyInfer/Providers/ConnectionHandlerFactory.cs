using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace AnyInfer.Providers;

/// <summary>Creates SDK-owned handlers and retains their connection certificate material.</summary>
internal static class ConnectionHandlerFactory
{
    private const string ServerAuthenticationOid = "1.3.6.1.5.5.7.3.1";

    internal static HttpMessageHandler CreateDefault(CancellationToken cancellationToken) =>
        Create(new ProviderConfig(ProviderSettings.Of("internal"), "internal", resolvedApiKey: null), cancellationToken);

    internal static HttpMessageHandler CreateOwned(ProviderConfig config, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(config);
        if (config.Transport is not null)
        {
            return config.Transport;
        }

        return Create(config, cancellationToken);
    }

    private static HttpMessageHandler Create(ProviderConfig config, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Redaction.RegisterSecret(config.Proxy?.UserName);
        Redaction.RegisterSecret(config.Proxy?.Password);
        Redaction.RegisterSecret(config.ClientCertificate?.Password);

        ConnectionMaterial? material = null;
        SocketsHttpHandler? handler = null;
        try
        {
            material = new ConnectionMaterial();
            handler = new SocketsHttpHandler { AllowAutoRedirect = false, UseCookies = false };
            ConfigureProxy(handler, config.Proxy);
            cancellationToken.ThrowIfCancellationRequested();
            ConfigureTls(handler, config, material, cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            var owned = new OwnedConnectionHandler(handler, material);
            handler = null;
            material = null;
            return owned;
        }
        catch (OperationCanceledException)
        {
            handler?.Dispose();
            material?.Dispose();
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or CryptographicException or ArgumentException)
        {
            handler?.Dispose();
            material?.Dispose();
            throw new ConfigException(
                "The provider connection settings are invalid.",
                config.ProviderId,
                "The configured CA bundle or client certificate could not be loaded.",
                "Check the configured PEM file paths and private-key password.",
                exception);
        }
        catch
        {
            handler?.Dispose();
            material?.Dispose();
            throw;
        }
    }

    private static void ConfigureProxy(SocketsHttpHandler handler, ProviderProxy? proxy)
    {
        if (proxy is null)
        {
            return;
        }

        var webProxy = new WebProxy(proxy.Address);
        if (proxy.UserName is not null || proxy.Password is not null)
        {
            webProxy.Credentials = new NetworkCredential(proxy.UserName ?? string.Empty, proxy.Password ?? string.Empty);
        }

        handler.UseProxy = true;
        handler.Proxy = webProxy;
    }

    private static void ConfigureTls(
        SocketsHttpHandler handler,
        ProviderConfig config,
        ConnectionMaterial material,
        CancellationToken cancellationToken)
    {
        if (config.Verify is null && config.ClientCertificate is null)
        {
            return;
        }

        var options = new SslClientAuthenticationOptions();
        if (config.Verify is { PemBundlePath: null })
        {
            options.RemoteCertificateValidationCallback = static (_, _, _, _) => true;
        }
        else if (config.Verify is { PemBundlePath: { } pemBundlePath })
        {
            options.CertificateChainPolicy = LoadCustomRoots(config.ProviderId, pemBundlePath, material, cancellationToken);
        }

        if (config.ClientCertificate is { } clientCertificate)
        {
            options.ClientCertificates = new X509CertificateCollection
            {
                LoadClientCertificate(clientCertificate, material, cancellationToken),
            };
        }

        handler.SslOptions = options;
    }

    private static X509ChainPolicy LoadCustomRoots(
        string providerId,
        string pemBundlePath,
        ConnectionMaterial material,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (Directory.Exists(pemBundlePath))
        {
            throw new ConfigException(
                "The provider connection settings are invalid.",
                providerId,
                detail: "CA directories are not supported by the native TLS implementation.",
                hint: "Configure a PEM CA-bundle file instead.");
        }

        var imported = new X509Certificate2Collection();
        try
        {
            imported.ImportFromPemFile(pemBundlePath);
            cancellationToken.ThrowIfCancellationRequested();
            if (imported.Count == 0)
            {
                throw new CryptographicException("The PEM CA bundle did not contain certificates.");
            }

            var policy = new X509ChainPolicy
            {
                TrustMode = X509ChainTrustMode.CustomRootTrust,
                RevocationMode = X509RevocationMode.NoCheck,
                DisableCertificateDownloads = true,
                VerificationFlags = X509VerificationFlags.NoFlag,
            };
            policy.ApplicationPolicy.Add(new Oid(ServerAuthenticationOid));
            foreach (var certificate in imported)
            {
                material.Adopt(certificate, cancellationToken);
                policy.CustomTrustStore.Add(certificate);
                cancellationToken.ThrowIfCancellationRequested();
            }

            return policy;
        }
        finally
        {
            // The material owner now owns every imported certificate on success; on failure
            // it disposes adopted entries, while unadopted entries remain ours to dispose.
            foreach (var certificate in imported)
            {
                if (!material.Contains(certificate))
                {
                    certificate.Dispose();
                }
            }
        }
    }

    private static X509Certificate2 LoadClientCertificate(
        ClientCertificate clientCertificate,
        ConnectionMaterial material,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        X509Certificate2? sourceCertificate = clientCertificate switch
        {
            { PrivateKeyPath: null } => X509Certificate2.CreateFromPemFile(clientCertificate.CertificatePath),
            { Password: null } => X509Certificate2.CreateFromPemFile(clientCertificate.CertificatePath, clientCertificate.PrivateKeyPath),
            _ => X509Certificate2.CreateFromEncryptedPemFile(
                clientCertificate.CertificatePath,
                clientCertificate.Password,
                clientCertificate.PrivateKeyPath),
        };
        X509Certificate2? finalCertificate = sourceCertificate;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (OperatingSystem.IsWindows())
            {
                byte[]? pkcs12 = null;
                X509Certificate2? replacementCertificate = null;
                try
                {
                    pkcs12 = sourceCertificate!.Export(X509ContentType.Pkcs12);
                    cancellationToken.ThrowIfCancellationRequested();
                    replacementCertificate = new X509Certificate2(
                        pkcs12,
                        (string?)null,
                        X509KeyStorageFlags.UserKeySet);
                    cancellationToken.ThrowIfCancellationRequested();
                    finalCertificate = replacementCertificate;
                    replacementCertificate = null;
                    sourceCertificate!.Dispose();
                    sourceCertificate = null;
                }
                finally
                {
                    replacementCertificate?.Dispose();
                    if (pkcs12 is not null)
                    {
                        CryptographicOperations.ZeroMemory(pkcs12);
                    }
                }
            }

            cancellationToken.ThrowIfCancellationRequested();
            material.Adopt(finalCertificate!, cancellationToken);
            return finalCertificate!;
        }
        catch
        {
            if (finalCertificate is not null && !material.Contains(finalCertificate))
            {
                finalCertificate.Dispose();
            }

            if (sourceCertificate is not null && !ReferenceEquals(sourceCertificate, finalCertificate))
            {
                sourceCertificate.Dispose();
            }

            throw;
        }
    }

    internal sealed class ConnectionMaterial : IDisposable
    {
        private readonly List<X509Certificate2> _certificates = [];
        private int _disposed;

        internal void Adopt(X509Certificate2 certificate, CancellationToken cancellationToken)
        {
            _certificates.Add(certificate);
            cancellationToken.ThrowIfCancellationRequested();
        }

        internal bool Contains(X509Certificate2 certificate) =>
            _certificates.Any(ownedCertificate => ReferenceEquals(ownedCertificate, certificate));

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
            {
                return;
            }

            foreach (var certificate in _certificates)
            {
                certificate.Dispose();
            }

            _certificates.Clear();
        }
    }

    private sealed class OwnedConnectionHandler(HttpMessageHandler innerHandler, ConnectionMaterial material) : DelegatingHandler(innerHandler)
    {
        private readonly ConnectionMaterial _material = material;
        private int _disposed;

        protected override void Dispose(bool disposing)
        {
            if (disposing && Interlocked.Exchange(ref _disposed, 1) == 0)
            {
                try
                {
                    base.Dispose(disposing);
                }
                finally
                {
                    _material.Dispose();
                }

                return;
            }

            base.Dispose(disposing);
        }
    }
}
