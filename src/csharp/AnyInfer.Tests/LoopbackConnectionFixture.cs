using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Runtime.ExceptionServices;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace AnyInfer.Tests;

/// <summary>Loopback server certificate variants for real platform-validation controls.</summary>
internal enum LoopbackTlsVariant
{
    Valid,
    WrongHostname,
    WrongServerEku,
    ExpiredLeaf,
    ExpiredRoot,
}

/// <summary>Test-only loopback HTTPS origin and CONNECT proxy with synthetic certificate material.</summary>
internal sealed class LoopbackConnectionFixture : IAsyncDisposable
{
    private readonly CancellationTokenSource _stopping = new();
    private readonly TcpListener _origin;
    private readonly TcpListener _proxy;
    private readonly TcpListener _secureProxy;
    private readonly X509Certificate2 _rootCertificate;
    private readonly X509Certificate2 _certificate;
    private readonly X509Certificate2 _clientCertificate;
    private readonly Task _originLoop;
    private readonly Task _proxyLoop;
    private readonly Task _secureProxyLoop;
    private readonly List<Task> _connections = [];
    private readonly object _connectionsGate = new();
    private readonly string _directory;

    private LoopbackConnectionFixture(bool requireClientCertificate, LoopbackTlsVariant variant)
    {
        RequireClientCertificate = requireClientCertificate;
        _directory = Path.Combine(Path.GetTempPath(), "anyinfer-connection-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_directory);
        (_rootCertificate, _certificate) = CreateServerCertificate(variant);
        _clientCertificate = CreateCertificate(clientAuthentication: true);
        CertificatePemPath = Path.Combine(_directory, "server.pem");
        File.WriteAllText(CertificatePemPath, _rootCertificate.ExportCertificatePem());
        ClientCertificatePemPath = Path.Combine(_directory, "client-combined.pem");
        ClientCertificatePath = Path.Combine(_directory, "client.pem");
        ClientPrivateKeyPath = Path.Combine(_directory, "client-key.pem");
        EncryptedClientPrivateKeyPath = Path.Combine(_directory, "client-key-encrypted.pem");
        EncryptedClientCertificatePemPath = Path.Combine(_directory, "client-encrypted-combined.pem");
        File.WriteAllText(ClientCertificatePath, _clientCertificate.ExportCertificatePem());
        using var clientKey = _clientCertificate.GetRSAPrivateKey()
            ?? throw new CryptographicException("The fixture client certificate has no RSA private key.");
        var clientKeyPem = clientKey.ExportPkcs8PrivateKeyPem();
        var encryptedClientKeyPem = clientKey.ExportEncryptedPkcs8PrivateKeyPem(
            "fixture-password",
            new PbeParameters(PbeEncryptionAlgorithm.Aes256Cbc, HashAlgorithmName.SHA256, 1_000));
        File.WriteAllText(ClientPrivateKeyPath, EnsurePemBlock(clientKeyPem));
        File.WriteAllText(ClientCertificatePemPath, JoinPemBlocks(_clientCertificate.ExportCertificatePem(), clientKeyPem));
        File.WriteAllText(EncryptedClientPrivateKeyPath, encryptedClientKeyPem);
        File.WriteAllText(EncryptedClientCertificatePemPath, JoinPemBlocks(_clientCertificate.ExportCertificatePem(), encryptedClientKeyPem));

        _origin = new TcpListener(IPAddress.Loopback, 0);
        _origin.Start();
        _proxy = new TcpListener(IPAddress.Loopback, 0);
        _proxy.Start();
        _secureProxy = new TcpListener(IPAddress.Loopback, 0);
        _secureProxy.Start();
        OriginUri = new Uri($"https://localhost:{((IPEndPoint)_origin.LocalEndpoint).Port}/v1/");
        ProxyUri = new Uri($"http://127.0.0.1:{((IPEndPoint)_proxy.LocalEndpoint).Port}/");
        SecureProxyUri = new Uri($"https://localhost:{((IPEndPoint)_secureProxy.LocalEndpoint).Port}/");
        _originLoop = AcceptOriginAsync();
        _proxyLoop = AcceptProxyAsync(_proxy, secure: false);
        _secureProxyLoop = AcceptProxyAsync(_secureProxy, secure: true);
    }

    internal Uri OriginUri { get; }
    internal Uri ProxyUri { get; }
    internal Uri SecureProxyUri { get; }
    internal string DirectoryPath => _directory;
    internal string CertificatePemPath { get; }
    internal string ClientCertificatePemPath { get; }
    internal string ClientCertificatePath { get; }
    internal string ClientPrivateKeyPath { get; }
    internal string EncryptedClientPrivateKeyPath { get; }
    internal string EncryptedClientCertificatePemPath { get; }
    internal bool RequireClientCertificate { get; }

    internal string WriteMaterial(string fileName, string contents)
    {
        var path = Path.Combine(_directory, fileName);
        File.WriteAllText(path, contents);
        return path;
    }
    internal int OriginRequests => Volatile.Read(ref _originRequests);
    internal int ProxyConnects => Volatile.Read(ref _proxyConnects);
    internal int ProxyChallenges => Volatile.Read(ref _proxyChallenges);
    internal int ProxyAuthenticatedConnects => Volatile.Read(ref _proxyAuthenticatedConnects);
    internal int ProxySuccessfulForwards => Volatile.Read(ref _proxySuccessfulForwards);
    internal int ProxyAuthorizationHeaders => Volatile.Read(ref _proxyAuthorizationHeaders);
    internal int ClientCertificates => Volatile.Read(ref _clientCertificates);
    internal int TlsHandshakeRejections => Volatile.Read(ref _tlsHandshakeRejections);
    private int _originRequests;
    private int _proxyConnects;
    private int _proxyChallenges;
    private int _proxyAuthenticatedConnects;
    private int _proxySuccessfulForwards;
    private int _proxyAuthorizationHeaders;
    private int _clientCertificates;
    private int _tlsHandshakeRejections;
    private string? _originAuthorization;
    private int _originReceivedProxyAuthorization;

    internal string? OriginAuthorization => Volatile.Read(ref _originAuthorization);
    internal bool OriginReceivedProxyAuthorization => Volatile.Read(ref _originReceivedProxyAuthorization) != 0;

    internal static LoopbackConnectionFixture Start(
        bool requireClientCertificate = false,
        LoopbackTlsVariant variant = LoopbackTlsVariant.Valid) =>
        new(requireClientCertificate, variant);

    public async ValueTask DisposeAsync()
    {
        _stopping.Cancel();
        _origin.Stop();
        _proxy.Stop();
        _secureProxy.Stop();
        await IgnoreStopAsync(_originLoop);
        await IgnoreStopAsync(_proxyLoop);
        await IgnoreStopAsync(_secureProxyLoop);
        Task[] connections;
        lock (_connectionsGate)
        {
            connections = [.. _connections];
        }
        foreach (var connection in connections)
        {
            await IgnoreStopAsync(connection);
        }
        _rootCertificate.Dispose();
        _certificate.Dispose();
        _clientCertificate.Dispose();
        try { Directory.Delete(_directory, recursive: true); } catch (IOException) { }
        _stopping.Dispose();
    }

    private async Task AcceptOriginAsync()
    {
        while (!_stopping.IsCancellationRequested)
        {
            try
            {
                var client = await _origin.AcceptTcpClientAsync(_stopping.Token);
                Track(HandleOriginAsync(client));
            }
            catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
            catch (SocketException) when (_stopping.IsCancellationRequested) { }
        }
    }

    private async Task HandleOriginAsync(TcpClient client)
    {
        using var owned = client;
        await using var tls = new SslStream(client.GetStream(), leaveInnerStreamOpen: false, ValidateClientCertificate);
        try
        {
            await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
            {
                ServerCertificate = _certificate,
                ClientCertificateRequired = RequireClientCertificate,
                EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
            }, _stopping.Token);
            var (requestLine, headers) = await ReadHeadersAsync(tls, _stopping.Token);
            if (!IsHttpRequestLine(requestLine))
            {
                return;
            }

            headers.TryGetValue("Authorization", out var authorization);
            _originAuthorization = authorization;
            Volatile.Write(ref _originReceivedProxyAuthorization, headers.ContainsKey("Proxy-Authorization") ? 1 : 0);
            Interlocked.Increment(ref _originRequests);
            var response = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}");
            await tls.WriteAsync(response, _stopping.Token);
        }
        catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
        catch (IOException) { }
        catch (AuthenticationException) { Interlocked.Increment(ref _tlsHandshakeRejections); }
    }

    private bool ValidateClientCertificate(
        object sender,
        X509Certificate? certificate,
        X509Chain? chain,
        SslPolicyErrors errors)
    {
        _ = sender;
        _ = chain;
        _ = errors;
        if (!RequireClientCertificate)
        {
            return true;
        }

        var matches = certificate is not null &&
            CryptographicOperations.FixedTimeEquals(certificate.GetRawCertData(), _clientCertificate.RawData);
        if (matches)
        {
            Interlocked.Increment(ref _clientCertificates);
        }

        return matches;
    }

    private async Task AcceptProxyAsync(TcpListener listener, bool secure)
    {
        while (!_stopping.IsCancellationRequested)
        {
            try
            {
                var client = await listener.AcceptTcpClientAsync(_stopping.Token);
                Track(HandleProxyAsync(client, secure));
            }
            catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
            catch (SocketException) when (_stopping.IsCancellationRequested) { }
        }
    }

    private async Task HandleProxyAsync(TcpClient client, bool secure)
    {
        using var inbound = client;
        try
        {
            Stream input = client.GetStream();
            await using var tls = secure
                ? new SslStream(input, leaveInnerStreamOpen: false)
                : null;
            if (tls is not null)
            {
                await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
                {
                    ServerCertificate = _certificate,
                    EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
                }, _stopping.Token);
                input = tls;
            }

            var (requestLine, headers) = await ReadHeadersAsync(input, _stopping.Token);
            if (!requestLine.StartsWith("CONNECT ", StringComparison.Ordinal)) return;
            Interlocked.Increment(ref _proxyConnects);
            if (!headers.TryGetValue("Proxy-Authorization", out var proxyAuthorization) ||
                !string.Equals(proxyAuthorization, ExpectedProxyAuthorization, StringComparison.Ordinal))
            {
                await input.WriteAsync(Encoding.ASCII.GetBytes(
                    "HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm=\"fixture\"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"), _stopping.Token);
                Interlocked.Increment(ref _proxyChallenges);
                return;
            }

            Interlocked.Increment(ref _proxyAuthenticatedConnects);
            Interlocked.Increment(ref _proxyAuthorizationHeaders);
            using var upstream = new TcpClient();
            await upstream.ConnectAsync(IPAddress.Loopback, ((IPEndPoint)_origin.LocalEndpoint).Port, _stopping.Token);
            var output = upstream.GetStream();
            await input.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 200 Connection Established\r\n\r\n"), _stopping.Token);
            Interlocked.Increment(ref _proxySuccessfulForwards);
            using var pumpStopping = CancellationTokenSource.CreateLinkedTokenSource(_stopping.Token);
            var upstreamPump = input.CopyToAsync(output, pumpStopping.Token);
            var downstreamPump = output.CopyToAsync(input, pumpStopping.Token);
            Exception? pumpFailure = null;
            try
            {
                var completed = await Task.WhenAny(upstreamPump, downstreamPump);
                await completed;
            }
            catch (Exception exception)
            {
                pumpFailure = exception;
            }
            finally
            {
                pumpStopping.Cancel();
                try
                {
                    await Task.WhenAll(
                        JoinPumpAsync(upstreamPump, pumpStopping.Token),
                        JoinPumpAsync(downstreamPump, pumpStopping.Token));
                }
                catch (Exception cleanupFailure)
                {
                    pumpFailure ??= cleanupFailure;
                }
            }

            if (pumpFailure is not null)
            {
                ExceptionDispatchInfo.Capture(pumpFailure).Throw();
            }
        }
        catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
        catch (IOException) when (_stopping.IsCancellationRequested) { }
        catch (SocketException) when (_stopping.IsCancellationRequested) { }
        catch (AuthenticationException) { Interlocked.Increment(ref _tlsHandshakeRejections); }
    }

    private static async Task<(string RequestLine, Dictionary<string, string> Headers)> ReadHeadersAsync(
        Stream stream,
        CancellationToken cancellationToken)
    {
        var requestLine = await ReadLineAsync(stream, cancellationToken);
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        while (true)
        {
            var line = await ReadLineAsync(stream, cancellationToken);
            if (line.Length == 0)
            {
                return (requestLine, headers);
            }

            var separator = line.IndexOf(':');
            if (separator > 0)
            {
                headers[line[..separator]] = line[(separator + 1)..].Trim();
            }
        }
    }

    private static bool IsHttpRequestLine(string requestLine) =>
        requestLine.Contains(" HTTP/1.", StringComparison.Ordinal) &&
        (requestLine.StartsWith("POST ", StringComparison.Ordinal) ||
         requestLine.StartsWith("GET ", StringComparison.Ordinal));

    private const string ExpectedProxyAuthorization = "Basic cHJveHktdXNlcjpwcm94eS1wYXNzd29yZA==";

    private static async ValueTask<string> ReadLineAsync(Stream stream, CancellationToken cancellationToken)
    {
        var bytes = new List<byte>();
        var one = new byte[1];
        while (true)
        {
            var read = await stream.ReadAsync(one, cancellationToken);
            if (read == 0) return string.Empty;
            if (one[0] == '\n') return Encoding.ASCII.GetString(bytes.ToArray()).TrimEnd('\r');
            bytes.Add(one[0]);
        }
    }

    private static (X509Certificate2 Root, X509Certificate2 Server) CreateServerCertificate(LoopbackTlsVariant variant)
    {
        var now = DateTimeOffset.UtcNow;
        var rootNotBefore = variant == LoopbackTlsVariant.ExpiredRoot ? now.AddDays(-30) : now.AddDays(-30);
        var rootNotAfter = variant == LoopbackTlsVariant.ExpiredRoot ? now.AddDays(-1) : now.AddDays(30);
        var leafNotBefore = variant switch
        {
            LoopbackTlsVariant.ExpiredLeaf => now.AddDays(-2),
            LoopbackTlsVariant.ExpiredRoot => now.AddMinutes(-1),
            _ => now.AddMinutes(-1),
        };
        var leafNotAfter = variant switch
        {
            LoopbackTlsVariant.ExpiredLeaf => now.AddDays(-1),
            LoopbackTlsVariant.ExpiredRoot => now.AddDays(1),
            _ => now.AddDays(1),
        };
        using var rootKey = RSA.Create(2048);
        var rootRequest = new CertificateRequest("CN=AnyInfer test root", rootKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        rootRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
        rootRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
        using var root = rootRequest.CreateSelfSigned(rootNotBefore, rootNotAfter);
        using var serverKey = RSA.Create(2048);
        var serverRequest = new CertificateRequest("CN=localhost", serverKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        serverRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        serverRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
        serverRequest.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(new OidCollection
        {
            new(variant == LoopbackTlsVariant.WrongServerEku ? "1.3.6.1.5.5.7.3.2" : "1.3.6.1.5.5.7.3.1"),
        }, true));
        var names = new SubjectAlternativeNameBuilder();
        names.AddDnsName(variant == LoopbackTlsVariant.WrongHostname ? "wrong-host.invalid" : "localhost");
        serverRequest.CertificateExtensions.Add(names.Build());
        var serial = RandomNumberGenerator.GetBytes(16);
        var signatureGenerator = X509SignatureGenerator.CreateForRSA(rootKey, RSASignaturePadding.Pkcs1);
        using var publicServer = serverRequest.Create(
            root.SubjectName,
            signatureGenerator,
            leafNotBefore,
            leafNotAfter,
            serial);
        using var generatedServer = publicServer.CopyWithPrivateKey(serverKey);
        var serverPfx = generatedServer.Export(X509ContentType.Pkcs12);
        try
        {
            var server = new X509Certificate2(
                serverPfx,
                password: string.Empty,
                X509KeyStorageFlags.DefaultKeySet | X509KeyStorageFlags.Exportable);
            return (new X509Certificate2(root.Export(X509ContentType.Cert)), server);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(serverPfx);
        }
    }

    private static X509Certificate2 CreateCertificate(bool clientAuthentication)
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=localhost", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
        var usage = new OidCollection { new(clientAuthentication ? "1.3.6.1.5.5.7.3.2" : "1.3.6.1.5.5.7.3.1") };
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(usage, true));
        if (!clientAuthentication) throw new ArgumentOutOfRangeException(nameof(clientAuthentication));
        return request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-1), DateTimeOffset.UtcNow.AddDays(1));
    }

    private static async Task IgnoreStopAsync(Task task)
    {
        try { await task; } catch (OperationCanceledException) { } catch (SocketException) { }
    }

    private static async Task JoinPumpAsync(Task pump, CancellationToken cancellationToken)
    {
        try { await pump; }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (IOException) when (cancellationToken.IsCancellationRequested) { }
    }

    private static string EnsurePemBlock(string value) => value.TrimEnd() + "\n";

    private static string JoinPemBlocks(params string[] values) =>
        string.Join("\n", values.Select(static value => value.Trim())) + "\n";

    private void Track(Task connection)
    {
        lock (_connectionsGate)
        {
            _connections.Add(connection);
        }
    }
}
