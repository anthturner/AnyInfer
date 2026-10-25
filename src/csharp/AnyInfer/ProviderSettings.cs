using AnyInfer.Json;
using AnyInfer.Routing;
using System.Collections.ObjectModel;
using System.Net.Http;

namespace AnyInfer;

/// <summary>Immutable configuration for one provider engine or named instance.</summary>
/// <remarks>
/// Constructing settings performs no I/O: credentials are not resolved, the provider identifier is
/// not looked up, and connection files are not read. A client validates the settings against its
/// provider registry when it is constructed, and resolves <see cref="ApiKey"/> and secret option
/// values through its credential resolver chain when the provider instance is first created.
/// <see cref="ToString"/> prints only <see cref="InstanceId"/>.
/// </remarks>
public sealed record ProviderSettings
{
    /// <summary>Creates immutable settings for one configured provider instance.</summary>
    /// <param name="providerId">Provider (engine) identifier, such as <c>openai</c>; it is trimmed, lowercased, and has underscores replaced by hyphens.</param>
    /// <param name="baseUrl">Absolute provider API base URL, or <see langword="null"/> to use the provider's default; the provider validates it when the instance is created.</param>
    /// <param name="apiKey">Literal credential or credential reference such as <c>env://NAME</c>, or <see langword="null"/> for none. It is resolved only when the provider instance is first created; do not log this value.</param>
    /// <param name="apiVersion">Provider API version, or <see langword="null"/> for the provider default.</param>
    /// <param name="headers">Extra request headers, copied into a case-insensitive read-only dictionary; <see langword="null"/> for none. Values are sent as given and are not registered for redaction.</param>
    /// <param name="options">Descriptor-defined provider options, or <see langword="null"/> for none. Values for fields the provider declares as secret are resolved like <paramref name="apiKey"/>; other values are passed through verbatim.</param>
    /// <param name="timeoutS">Per-request timeout in seconds; it must be finite and positive. Defaults to 120.</param>
    /// <param name="transport">HTTP handler to use instead of one the SDK creates, or <see langword="null"/> for an SDK-created handler. Ownership transfers to AnyInfer, one handler may serve only one configured instance, and a supplied handler bypasses <paramref name="proxy"/>, <paramref name="verify"/>, and <paramref name="clientCertificate"/>.</param>
    /// <param name="alias">Instance identifier used in target strings when the same engine is configured more than once, normalized like <paramref name="providerId"/>; <see langword="null"/> uses the provider identifier.</param>
    /// <param name="limits">Client-side pacing for this instance, or <see langword="null"/> for none.</param>
    /// <param name="proxy">Explicit proxy for the SDK-created handler, or <see langword="null"/> to keep the .NET default proxy behavior.</param>
    /// <param name="verify">TLS verification override for the SDK-created handler, or <see langword="null"/> to keep platform certificate verification.</param>
    /// <param name="clientCertificate">PEM client certificate for the SDK-created handler, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="providerId"/> is <see langword="null"/>, or a header value is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="providerId"/> or <paramref name="alias"/> is blank, a header name is empty, or two header names differ only by case.</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="timeoutS"/> is not finite or not positive.</exception>
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
    /// <inheritdoc cref="ProviderSettings(string, string, string, string, IReadOnlyDictionary{string, string}, JsonObject, double, HttpMessageHandler, string, RateLimits, ProviderProxy, TlsVerification, ClientCertificate)"/>
    /// <returns>New settings, exactly as the constructor would create them.</returns>
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

    /// <summary>Returns a credential-safe, identity-only representation.</summary>
    /// <returns><c>ProviderSettings(</c> followed by <see cref="InstanceId"/> and <c>)</c>; credentials, headers, options, URLs, and connection settings are omitted.</returns>
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
