using System.Net;
using System.Net.Http;
using AnyInfer.Config;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public value and copy controls for per-instance native connection settings.</summary>
public sealed class ConnectionSettingsTests
{
    [Fact]
    public void Proxy_parse_decodes_connection_values_but_keeps_an_exact_config_literal_and_safe_display()
    {
        var proxy = ProviderProxy.Parse("  https://user%20name:pass%3Aword@MiXeD.Proxy.invalid:443/  ");

        Assert.Equal("https", proxy.Address.Scheme);
        Assert.Equal("mixed.proxy.invalid", proxy.Address.Host);
        Assert.Equal(443, proxy.Address.Port);
        Assert.Equal("user name", proxy.UserName);
        Assert.Equal("pass:word", proxy.Password);
        Assert.Equal("https://user%20name:pass%3Aword@MiXeD.Proxy.invalid:443/", proxy.ConfigurationValue);
        Assert.Equal("ProviderProxy", proxy.ToString());
        Assert.DoesNotContain("user", proxy.ToString(), StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("pass", proxy.ToString(), StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("socks5://proxy.invalid")]
    [InlineData("https://proxy.invalid/path")]
    [InlineData("https://proxy.invalid/?query=true")]
    [InlineData("https://proxy.invalid/#fragment")]
    [InlineData("not-a-uri")]
    public void Proxy_parse_rejects_unsupported_shapes_without_echoing_the_input(string literal)
    {
        var failure = Assert.Throws<ArgumentException>(() => ProviderProxy.Parse(literal));

        Assert.DoesNotContain(literal, failure.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Direct_proxy_tls_and_client_certificate_values_are_immutable_safe_and_inert()
    {
        var address = new Uri("https://Proxy.invalid:443/");
        var proxy = new ProviderProxy(address, "user", "password");
        var verify = TlsVerification.FromPemBundle("  fixture-ca.pem  ");
        var combined = ClientCertificate.FromPemFile("  combined.pem  ");
        var pair = ClientCertificate.FromPemPair(" certificate.pem ", " key.pem ");
        var encrypted = ClientCertificate.FromEncryptedPemPair("certificate.pem", "key.pem", "password");

        Assert.Equal(address, proxy.Address);
        Assert.Equal("user", proxy.UserName);
        Assert.Equal("password", proxy.Password);
        Assert.Equal("fixture-ca.pem", verify.PemBundlePath);
        Assert.Equal("  combined.pem  ", combined.CertificatePath);
        Assert.Null(combined.PrivateKeyPath);
        Assert.Equal(" certificate.pem ", pair.CertificatePath);
        Assert.Equal(" key.pem ", pair.PrivateKeyPath);
        Assert.Equal("password", encrypted.Password);
        Assert.Equal("TlsVerification.PemBundle", verify.ToString());
        Assert.Equal("TlsVerification.Disabled", TlsVerification.Disabled.ToString());
        Assert.Equal("ClientCertificate.PemFile", combined.ToString());
        Assert.Equal("ClientCertificate.PemPair", pair.ToString());
        Assert.Equal("ClientCertificate.EncryptedPemPair", encrypted.ToString());
        Assert.DoesNotContain("fixture", verify.ToString(), StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("password", encrypted.ToString(), StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Direct_typed_proxy_settings_dump_and_reload_with_escaped_credentials_and_colon_password()
    {
        var proxy = new ProviderProxy(
            new Uri("https://proxy.invalid:8443/"),
            "typed user",
            "typed:password");
        var settings = ProviderSettings.Of("openai-compat", "https://service.invalid/v1", proxy: proxy);
        var dump = new AnyInferConfig([settings]).Dumps();
        var restored = Assert.Single(AnyInferConfig.Loads(dump, ProviderRegistry.CreateDefault()).Providers);

        Assert.Contains(proxy.ConfigurationValue, dump, StringComparison.Ordinal);
        Assert.Equal(proxy.ConfigurationValue, restored.Proxy!.ConfigurationValue);
        Assert.Equal(proxy.UserName, restored.Proxy.UserName);
        Assert.Equal(proxy.Password, restored.Proxy.Password);
    }

    [Fact]
    public void Blank_tls_and_empty_certificate_values_are_rejected_before_file_access()
    {
        Assert.Throws<ArgumentException>(() => TlsVerification.FromPemBundle(" "));
        Assert.Throws<ArgumentException>(() => ClientCertificate.FromPemFile(string.Empty));
        Assert.Throws<ArgumentException>(() => ClientCertificate.FromPemPair(string.Empty, "key.pem"));
        Assert.Throws<ArgumentException>(() => ClientCertificate.FromPemPair("certificate.pem", string.Empty));
        Assert.Throws<ArgumentException>(() => ClientCertificate.FromEncryptedPemPair(string.Empty, "key.pem", "password"));
        Assert.Throws<ArgumentException>(() => ClientCertificate.FromEncryptedPemPair("certificate.pem", string.Empty, "password"));
        Assert.Throws<ArgumentException>(() => ClientCertificate.FromEncryptedPemPair("certificate.pem", "key.pem", string.Empty));
        Assert.Equal(" ", ClientCertificate.FromEncryptedPemPair("certificate.pem", "key.pem", " ").Password);
    }

    [Fact]
    public void Settings_and_adapter_config_preserve_all_connection_values_through_transport_copy()
    {
        var proxy = ProviderProxy.Parse("https://user:password@proxy.invalid:443/");
        var verify = TlsVerification.FromPemBundle("fixture-ca.pem");
        var certificate = ClientCertificate.FromEncryptedPemPair("certificate.pem", "key.pem", "password");
        var settings = ProviderSettings.Of(
            "fake",
            "https://service.invalid/v1",
            "api-key",
            proxy: proxy,
            verify: verify,
            clientCertificate: certificate);
        var config = new ProviderConfig(settings, "fake", "resolved-key");
        var handler = new CapturingHandler();
        var copied = config.WithTransport(handler, transportOwnedByPool: true);

        Assert.Same(proxy, settings.Proxy);
        Assert.Same(verify, settings.Verify);
        Assert.Same(certificate, settings.ClientCertificate);
        Assert.Same(proxy, config.Proxy);
        Assert.Same(verify, config.Verify);
        Assert.Same(certificate, config.ClientCertificate);
        Assert.Same(proxy, copied.Proxy);
        Assert.Same(verify, copied.Verify);
        Assert.Same(certificate, copied.ClientCertificate);
        Assert.Same(handler, copied.Transport);
        Assert.True(copied.TransportOwnedByPool);
    }

    private sealed class CapturingHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("The connection-value copy control must not dispatch.");
    }
}
