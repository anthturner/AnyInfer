using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>Builds inert provider connection settings and round-trips them through version 1 JSON.</summary>
public static class ConnectionExample
{
    /// <summary>Checks safe diagnostic representations and lossless connection configuration fields.</summary>
    public static bool VerifyRoundTrip()
    {
        var proxy = ProviderProxy.Parse("https://demo-user:demo-password@proxy.example:8443");
        var verify = TlsVerification.FromPemBundle("./certs/private-ca.pem");
        var certificate = ClientCertificate.FromEncryptedPemPair(
            "./certs/client.pem",
            "./certs/client.pem",
            "example-password");
        var settings = ProviderSettings.Of(
            "openai-compat",
            baseUrl: "https://api.example/v1",
            proxy: proxy,
            verify: verify,
            clientCertificate: certificate);

        // This example constructs and serializes settings only. It never creates a client
        // or loads these illustrative paths as TLS material.
        var json = new AnyInferConfig([settings]).Dumps();
        var restored = AnyInferConfig.Loads(json).Providers.Single();
        return settings.ToString() == "ProviderSettings(openai-compat)"
            && proxy.ToString() == "ProviderProxy"
            && verify.ToString() == "TlsVerification.PemBundle"
            && certificate.ToString() == "ClientCertificate.EncryptedPemPair"
            && json.Contains("https://demo-user:demo-password@proxy.example:8443", StringComparison.Ordinal)
            && json.Contains("example-password", StringComparison.Ordinal)
            && new AnyInferConfig([restored]).Dumps() == json;
    }
}
