using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using AnyInfer.Config;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Routing;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public-client controls for owned proxy and TLS handler materialization.</summary>
public sealed class ConnectionTransportTests
{
    [Fact]
    public async Task Custom_pem_bundle_reaches_the_loopback_origin_only_after_stream_advancement()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        await using var client = OpenAiClient(
            fixture.OriginUri,
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath));

        var stream = client.StreamAsync("inert", target: "openai-compat:model");
        Assert.Equal(0, fixture.OriginRequests);

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => stream.CollectAsync().WaitAsync(TimeSpan.FromSeconds(15)));
        Assert.Equal(1, fixture.OriginRequests);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Explicit_proxy_authenticates_separately_from_the_origin_bearer_credential(bool secureProxy)
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        var proxy = new ProviderProxy(secureProxy ? fixture.SecureProxyUri : fixture.ProxyUri, "proxy-user", "proxy-password");
        await using var client = OpenAiClient(
            fixture.OriginUri,
            proxy: proxy,
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => GenerateWithinAsync(client, "proxy", "openai-compat:model"));

        Assert.Equal(1, fixture.ProxySuccessfulForwards);
        Assert.Equal(1, fixture.ProxyAuthorizationHeaders);
        Assert.Equal(2, fixture.ProxyConnects);
        Assert.Equal(1, fixture.ProxyChallenges);
        Assert.Equal(1, fixture.ProxyAuthenticatedConnects);
        Assert.Equal(1, fixture.OriginRequests);
        Assert.Equal("Bearer key", fixture.OriginAuthorization);
        Assert.False(fixture.OriginReceivedProxyAuthorization);
    }

    [Theory]
    [InlineData("combined")]
    [InlineData("pair")]
    [InlineData("encrypted-pair")]
    [InlineData("encrypted-same-path")]
    public async Task Supported_pem_client_certificate_shapes_are_presented_to_a_server_that_requires_one(string shape)
    {
        await using var fixture = LoopbackConnectionFixture.Start(requireClientCertificate: true);
        var certificate = shape switch
        {
            "combined" => ClientCertificate.FromPemFile(fixture.ClientCertificatePemPath),
            "pair" => ClientCertificate.FromPemPair(fixture.ClientCertificatePath, fixture.ClientPrivateKeyPath),
            "encrypted-pair" => ClientCertificate.FromEncryptedPemPair(
                fixture.ClientCertificatePath,
                fixture.EncryptedClientPrivateKeyPath,
                "fixture-password"),
            "encrypted-same-path" => ClientCertificate.FromEncryptedPemPair(
                fixture.EncryptedClientCertificatePemPath,
                fixture.EncryptedClientCertificatePemPath,
                "fixture-password"),
            _ => throw new ArgumentOutOfRangeException(nameof(shape)),
        };
        await using var client = OpenAiClient(
            fixture.OriginUri,
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath),
            clientCertificate: certificate);

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => GenerateWithinAsync(client, "mtls", "openai-compat:model"));

        Assert.Equal(1, fixture.ClientCertificates);
        Assert.Equal(1, fixture.OriginRequests);
    }

    [Fact]
    public async Task Owned_handler_pair_client_certificate_completes_a_real_loopback_http_request()
    {
        await using var fixture = LoopbackConnectionFixture.Start(requireClientCertificate: true);
        var settings = ProviderSettings.Of(
            "openai-compat",
            fixture.OriginUri.ToString(),
            "key",
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath),
            clientCertificate: ClientCertificate.FromPemPair(
                fixture.ClientCertificatePath,
                fixture.ClientPrivateKeyPath));
        var config = new ProviderConfig(settings, "openai-compat", "key");
        using var caller = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var client = new HttpClient(
            ConnectionHandlerFactory.CreateOwned(config, caller.Token),
            disposeHandler: true);
        using var request = new HttpRequestMessage(HttpMethod.Post, fixture.OriginUri)
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        };

        using var response = await client.SendAsync(request, caller.Token).WaitAsync(TimeSpan.FromSeconds(15));
        var body = await response.Content.ReadAsStringAsync(caller.Token).WaitAsync(TimeSpan.FromSeconds(15));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("{}", body);
        Assert.Equal(1, fixture.ClientCertificates);
        Assert.Equal(1, fixture.OriginRequests);
    }

    [Fact]
    public async Task Disabled_verification_is_per_instance_and_an_injected_handler_skips_invalid_material_loading()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        await using var defaultClient = OpenAiClient(fixture.OriginUri);
        await using var disabled = OpenAiClient(fixture.OriginUri, verify: TlsVerification.Disabled);
        await Assert.ThrowsAsync<AllTargetsFailedException>(() => GenerateWithinAsync(disabled, "disabled", "openai-compat:model"));
        Assert.Equal(1, fixture.OriginRequests);
        await Assert.ThrowsAsync<AllTargetsFailedException>(() => GenerateWithinAsync(defaultClient, "default", "openai-compat:model"));
        Assert.Equal(1, fixture.OriginRequests);

        var handler = new OpenAiResponseHandler();
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var factoryCalls = 0;
        var descriptor = new ProviderDescriptor(
            builtin.Id,
            builtin.DisplayName,
            (config, token) =>
            {
                factoryCalls++;
                return builtin.Factory(config, token);
            },
            defaultBaseUrl: "https://fixture.invalid/v1",
            requiresBaseUrl: true,
            honorsConnectionSettings: false);
        var settings = ProviderSettings.Of(
            "openai-compat",
            "https://fixture.invalid/v1",
            "key",
            transport: handler,
            verify: TlsVerification.FromPemBundle("definitely-not-loaded.pem"),
            clientCertificate: ClientCertificate.FromPemFile("also-not-loaded.pem"));
        await using var injected = new AsyncClient([settings], new ProviderRegistry([descriptor]));

        Assert.Equal("ok", (await injected.GenerateAsync("takeover", target: "openai-compat:model")).Text);
        Assert.Equal(1, factoryCalls);
        Assert.Equal(1, handler.SendCalls);
    }

    [Fact]
    public async Task Default_and_unrelated_custom_roots_do_not_bypass_platform_validation()
    {
        await using var origin = LoopbackConnectionFixture.Start();
        await using var unrelated = LoopbackConnectionFixture.Start();
        await using var defaultClient = OpenAiClient(origin.OriginUri);
        await using var wrongRootClient = OpenAiClient(
            origin.OriginUri,
            verify: TlsVerification.FromPemBundle(unrelated.CertificatePemPath));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => GenerateWithinAsync(defaultClient, "default", "openai-compat:model"));
        await Assert.ThrowsAsync<AllTargetsFailedException>(() => GenerateWithinAsync(wrongRootClient, "wrong-root", "openai-compat:model"));
        Assert.Equal(0, origin.OriginRequests);
    }

    [Theory]
    [InlineData((int)LoopbackTlsVariant.WrongHostname)]
    [InlineData((int)LoopbackTlsVariant.WrongServerEku)]
    [InlineData((int)LoopbackTlsVariant.ExpiredLeaf)]
    [InlineData((int)LoopbackTlsVariant.ExpiredRoot)]
    public async Task Enabled_custom_verification_rejects_each_invalid_certificate_variant_before_http_dispatch(
        int variantValue)
    {
        var variant = (LoopbackTlsVariant)variantValue;
        await using var fixture = LoopbackConnectionFixture.Start(variant: variant);
        await using var client = OpenAiClient(
            fixture.OriginUri,
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() =>
            GenerateWithinAsync(client, "invalid-certificate", "openai-compat:model"));

        Assert.Equal(0, fixture.OriginRequests);

        var settings = ProviderSettings.Of(
            "openai-compat",
            fixture.OriginUri.ToString(),
            "key",
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath));
        var config = new ProviderConfig(settings, "openai-compat", "key");
        using var caller = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var ownedClient = new HttpClient(
            ConnectionHandlerFactory.CreateOwned(config, caller.Token),
            disposeHandler: true);
        using var request = new HttpRequestMessage(HttpMethod.Post, fixture.OriginUri)
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        };
        var failure = await Assert.ThrowsAsync<HttpRequestException>(() =>
            ownedClient.SendAsync(request, caller.Token).WaitAsync(TimeSpan.FromSeconds(15)));

        Assert.True(
            failure.HttpRequestError == HttpRequestError.SecureConnectionError ||
            HasAuthenticationException(failure));
        Assert.Equal(0, fixture.OriginRequests);
    }

    [Fact]
    public void Pre_cancelled_owned_materialization_does_not_open_or_validate_the_configured_paths()
    {
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        var settings = ProviderSettings.Of(
            "openai-compat",
            "https://fixture.invalid/v1",
            verify: TlsVerification.FromPemBundle("not-opened-before-cancellation.pem"),
            clientCertificate: ClientCertificate.FromPemFile("also-not-opened-before-cancellation.pem"));
        var config = new ProviderConfig(settings, "openai-compat", null);

        var failure = Assert.Throws<OperationCanceledException>(() => ConnectionHandlerFactory.CreateOwned(config, cancelled.Token));
        Assert.Equal(cancelled.Token, failure.CancellationToken);
    }

    [Fact]
    public async Task Actual_imported_material_is_disposed_after_the_real_ownership_checkpoint_is_cancelled()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        var imported = new X509Certificate2Collection();
        imported.ImportFromPemFile(fixture.CertificatePemPath);
        var certificate = Assert.Single(imported);
        var material = new ConnectionHandlerFactory.ConnectionMaterial();
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();

        try
        {
            var failure = Assert.Throws<OperationCanceledException>(() => material.Adopt(certificate, cancelled.Token));
            Assert.Equal(cancelled.Token, failure.CancellationToken);
            Assert.True(material.Contains(certificate));
        }
        finally
        {
            material.Dispose();
        }

        Assert.Throws<CryptographicException>(() => certificate.Export(X509ContentType.Cert));
    }

    [Fact]
    public async Task Invalid_connection_material_fails_as_configuration_before_http_dispatch_without_path_leakage()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        var malformedCa = fixture.WriteMaterial("malformed-ca.pem", "not a PEM bundle");
        var missingKey = Path.Combine(fixture.DirectoryPath, "missing-key.pem");
        var wrongKey = fixture.WriteMaterial("wrong-key.pem", "-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----\n");
        var wrongPasswordKey = fixture.EncryptedClientPrivateKeyPath;
        var invalidClients = new[]
        {
            OpenAiClient(fixture.OriginUri, verify: TlsVerification.FromPemBundle(fixture.DirectoryPath)),
            OpenAiClient(fixture.OriginUri, verify: TlsVerification.FromPemBundle(malformedCa)),
            OpenAiClient(fixture.OriginUri, verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath), clientCertificate: ClientCertificate.FromPemPair(fixture.ClientCertificatePath, missingKey)),
            OpenAiClient(fixture.OriginUri, verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath), clientCertificate: ClientCertificate.FromPemPair(fixture.ClientCertificatePath, wrongKey)),
            OpenAiClient(fixture.OriginUri, verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath), clientCertificate: ClientCertificate.FromEncryptedPemPair(fixture.ClientCertificatePath, wrongPasswordKey, "wrong-password")),
        };

        foreach (var invalidClient in invalidClients)
        {
            await using (invalidClient)
            {
                var failure = await Assert.ThrowsAsync<ConfigException>(() => GenerateWithinAsync(invalidClient, "invalid-material", "openai-compat:model"));
                Assert.DoesNotContain(fixture.DirectoryPath, failure.ToString(), StringComparison.Ordinal);
            }
        }

        Assert.Equal(0, fixture.OriginRequests);
    }

    [Fact]
    public async Task Connection_materialization_redacts_short_and_long_proxy_and_pem_secrets_from_public_failures()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        var shortUserName = "u42";
        var longProxyPassword = new string('p', 40);
        var pemPassword = new string('k', 48);
        var settings = ProviderSettings.Of(
            "openai-compat",
            fixture.OriginUri.ToString(),
            "api-key",
            proxy: new ProviderProxy(fixture.ProxyUri, shortUserName, longProxyPassword),
            verify: TlsVerification.FromPemBundle(fixture.WriteMaterial("redaction-invalid-ca.pem", "not a PEM bundle")),
            clientCertificate: ClientCertificate.FromEncryptedPemPair(
                fixture.ClientCertificatePath,
                fixture.EncryptedClientPrivateKeyPath,
                pemPassword));
        var observer = new TelemetryCollector();
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault(), observers: [observer]);

        var failure = await Assert.ThrowsAsync<ConfigException>(() =>
            GenerateWithinAsync(client, "redaction", "openai-compat:model"));
        Assert.Single(observer.Events.OfType<RequestStarted>());
        Assert.Single(observer.Events.OfType<RequestFailed>());
        var configDump = new AnyInferConfig([settings]).Dumps();
        string[] representations =
        [
            failure.ToString(),
            failure.Snapshot().ToString(),
            .. observer.Events.Select(static item => JsonWriter.WriteManifestCanonical(item.ToDictionary())),
        ];

        foreach (var secret in new[] { shortUserName, longProxyPassword, pemPassword })
        {
            Assert.Contains(secret, configDump, StringComparison.Ordinal);
            Assert.All(representations, representation => Assert.DoesNotContain(secret, representation, StringComparison.Ordinal));
        }

        Assert.Equal(0, fixture.OriginRequests);
    }

    [Fact]
    public async Task Active_connection_settings_are_rejected_before_a_false_capability_factory_or_network_dispatch()
    {
        var calls = 0;
        var descriptor = new ProviderDescriptor(
            "unsupported",
            "Unsupported",
            (providerConfig, cancellationToken) =>
            {
                _ = providerConfig;
                _ = cancellationToken;
                calls++;
                return ValueTask.FromResult<IAsyncDisposable>(new EmptyAdapter());
            },
            defaultBaseUrl: "https://fixture.invalid/v1",
            honorsConnectionSettings: false);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("unsupported", proxy: ProviderProxy.Parse("https://proxy.invalid"))],
            new ProviderRegistry([descriptor]));

        await Assert.ThrowsAsync<ConfigException>(() => client.GenerateAsync("refuse", target: "unsupported:model"));
        Assert.Equal(0, calls);
    }

    [Fact]
    public async Task Each_retrieval_adapter_uses_the_same_owned_tls_handler_path()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        var verification = TlsVerification.FromPemBundle(fixture.CertificatePemPath);

        await AssertRetrievalDispatchAsync(Assert.IsType<TeiAdapter>(TeiAdapter.Create(
            Config("tei", fixture.OriginUri, verification), CancellationToken.None)));
        await AssertRetrievalDispatchAsync(Assert.IsType<VoyageAdapter>(VoyageAdapter.Create(
            Config("voyage", fixture.OriginUri, verification), CancellationToken.None)));
        await AssertRetrievalDispatchAsync(Assert.IsType<JinaAdapter>(JinaAdapter.Create(
            Config("jina", fixture.OriginUri, verification), CancellationToken.None)));

        Assert.Equal(3, fixture.OriginRequests);
    }

    private static AsyncClient OpenAiClient(
        Uri baseUri,
        ProviderProxy? proxy = null,
        TlsVerification? verify = null,
        ClientCertificate? clientCertificate = null) =>
        new(
            [ProviderSettings.Of("openai-compat", baseUri.ToString(), "key", proxy: proxy, verify: verify, clientCertificate: clientCertificate)],
            ProviderRegistry.CreateDefault());

    private static ProviderConfig Config(string provider, Uri baseUri, TlsVerification verify) =>
        new(ProviderSettings.Of(provider, baseUri.ToString(), "key", verify: verify), provider, "key");

    private static async Task GenerateWithinAsync(AsyncClient client, string prompt, string target)
    {
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await client.GenerateAsync(prompt, target: target, cancellationToken: budget.Token);
    }

    private static bool HasAuthenticationException(Exception exception) =>
        exception is System.Security.Authentication.AuthenticationException ||
        exception.InnerException is not null && HasAuthenticationException(exception.InnerException);

    private static async Task AssertRetrievalDispatchAsync(TeiAdapter adapter)
    {
        await using (adapter)
        {
            using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            await Assert.ThrowsAnyAsync<Exception>(() => adapter.EmbedAsync(
                new EmbeddingWireRequest("model", ["input"]), budget.Token).AsTask().WaitAsync(TimeSpan.FromSeconds(15)));
        }
    }

    private static async Task AssertRetrievalDispatchAsync(VoyageAdapter adapter)
    {
        await using (adapter)
        {
            using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            await Assert.ThrowsAnyAsync<Exception>(() => adapter.EmbedAsync(
                new EmbeddingWireRequest("model", ["input"]), budget.Token).AsTask().WaitAsync(TimeSpan.FromSeconds(15)));
        }
    }

    private static async Task AssertRetrievalDispatchAsync(JinaAdapter adapter)
    {
        await using (adapter)
        {
            using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            await Assert.ThrowsAnyAsync<Exception>(() => adapter.EmbedAsync(
                new EmbeddingWireRequest("model", ["input"]), budget.Token).AsTask().WaitAsync(TimeSpan.FromSeconds(15)));
        }
    }

    private sealed class OpenAiResponseHandler : HttpMessageHandler
    {
        internal int SendCalls { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCalls++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""",
                    Encoding.UTF8,
                    "application/json"),
            });
        }
    }

    private sealed class EmptyAdapter : IProviderAdapter
    {
        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            await Task.Yield();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class TelemetryCollector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];

        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }
}
