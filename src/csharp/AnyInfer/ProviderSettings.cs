using AnyInfer.Json;
using AnyInfer.Routing;
using System.Collections.ObjectModel;
using System.Net.Http;

namespace AnyInfer;

/// <summary>Immutable configuration for one provider engine or named instance.</summary>
public sealed record ProviderSettings
{
    public ProviderSettings(
        string providerId,
        string? baseUrl = null,
        string? apiKey = null,
        string? apiVersion = null,
        IReadOnlyDictionary<string, string>? headers = null,
        JsonObject? options = null,
        double timeoutS = 120,
        HttpMessageHandler? transport = null,
        string? alias = null,
        RateLimits? limits = null,
        ProviderProxy? proxy = null,
        TlsVerification? verify = null,
        ClientCertificate? clientCertificate = null)
    {
        ProviderId = NormalizeId(providerId, nameof(providerId));
        Alias = alias is null ? null : NormalizeId(alias, nameof(alias));
        BaseUrl = baseUrl;
        ApiKey = apiKey;
        ApiVersion = apiVersion;
        Headers = CopyHeaders(headers);
        Options = options;
        if (!double.IsFinite(timeoutS) || timeoutS <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(timeoutS), "Timeout must be finite and positive.");
        }

        TimeoutS = timeoutS;
        Transport = transport;
        Limits = limits;
        Proxy = proxy;
        Verify = verify;
        ClientCertificate = clientCertificate;
    }

    /// <summary>Gets the canonical descriptor identifier.</summary>
    public string ProviderId { get; }
    /// <summary>Gets the optional absolute provider API base URL.</summary>
    public string? BaseUrl { get; }
    /// <summary>Gets an API key literal or resolver reference; do not log this value.</summary>
    public string? ApiKey { get; }
    /// <summary>Gets the optional provider API version.</summary>
    public string? ApiVersion { get; }
    /// <summary>Gets immutable user headers applied to provider requests.</summary>
    public IReadOnlyDictionary<string, string> Headers { get; }
    /// <summary>Gets immutable descriptor-defined provider options.</summary>
    public JsonObject? Options { get; }
    /// <summary>Gets the per-instance request timeout in seconds.</summary>
    public double TimeoutS { get; }
    /// <summary>Gets the optional ownership-transferred HTTP transport test seam.</summary>
    public HttpMessageHandler? Transport { get; }
    /// <summary>Gets the optional distinct configured-instance alias.</summary>
    public string? Alias { get; }
    /// <summary>Gets optional client-side pacing limits for this configured instance.</summary>
    public RateLimits? Limits { get; }
    /// <summary>Gets optional explicit proxy settings for SDK-created transports.</summary>
    public ProviderProxy? Proxy { get; }
    /// <summary>Gets optional non-default TLS verification settings for SDK-created transports.</summary>
    public TlsVerification? Verify { get; }
    /// <summary>Gets optional PEM client-certificate settings for SDK-created transports.</summary>
    public ClientCertificate? ClientCertificate { get; }
    /// <summary>Gets the canonical configured-instance identity.</summary>
    public string InstanceId => Alias ?? ProviderId;

    internal bool HasActiveConnectionSettings => Proxy is not null || Verify is not null || ClientCertificate is not null;

    /// <summary>Creates immutable settings for one configured provider instance.</summary>
    public static ProviderSettings Of(
        string providerId,
        string? baseUrl = null,
        string? apiKey = null,
        string? apiVersion = null,
        IReadOnlyDictionary<string, string>? headers = null,
        JsonObject? options = null,
        double timeoutS = 120,
        HttpMessageHandler? transport = null,
        string? alias = null,
        RateLimits? limits = null,
        ProviderProxy? proxy = null,
        TlsVerification? verify = null,
        ClientCertificate? clientCertificate = null) =>
        new(providerId, baseUrl, apiKey, apiVersion, headers, options, timeoutS, transport, alias, limits, proxy, verify, clientCertificate);

    public override string ToString() => $"ProviderSettings({InstanceId})";

    internal static string NormalizeId(string value, string parameterName)
    {
        ArgumentNullException.ThrowIfNull(value);
        var normalized = value.Trim().ToLowerInvariant().Replace('_', '-');
        if (normalized.Length == 0)
        {
            throw new ArgumentException("Provider identifiers cannot be blank.", parameterName);
        }

        return normalized;
    }

    private static IReadOnlyDictionary<string, string> CopyHeaders(IReadOnlyDictionary<string, string>? headers)
    {
        var copy = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (headers is not null)
        {
            foreach (var (name, value) in headers)
            {
                ArgumentException.ThrowIfNullOrEmpty(name);
                ArgumentNullException.ThrowIfNull(value);
                if (!copy.TryAdd(name, value))
                {
                    throw new ArgumentException("Provider headers cannot differ only by case.", nameof(headers));
                }
            }
        }

        return new ReadOnlyDictionary<string, string>(copy);
    }
}
