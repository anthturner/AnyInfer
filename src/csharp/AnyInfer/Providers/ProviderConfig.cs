using AnyInfer.Json;
using AnyInfer.Routing;
using System.Collections.ObjectModel;
using System.Net.Http;

namespace AnyInfer.Providers;

/// <summary>Resolved adapter-facing configuration for one provider instance.</summary>
/// <remarks>
/// The client builds this after resolving the instance's credential and setup options, and passes it to the
/// descriptor's <see cref="ProviderDescriptor.Factory"/>. It holds a resolved secret in <see cref="ApiKey"/>,
/// which <see cref="ToString"/> never renders.
/// </remarks>
public sealed record ProviderConfig
{
    /// <summary>Creates adapter configuration from settings and already-resolved values.</summary>
    /// <param name="settings">Configured instance settings; the base URL, headers, timeout, transport, and connection settings are copied from it.</param>
    /// <param name="engineId">Descriptor provider identity serving the instance; trimmed, lower-cased, and with underscores replaced by hyphens.</param>
    /// <param name="resolvedApiKey">Resolved API secret, or <see langword="null"/> when the instance has none.</param>
    /// <param name="resolvedOptions">Resolved setup options, or <see langword="null"/> to use the options from <paramref name="settings"/>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="settings"/> or <paramref name="engineId"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="engineId"/> is blank.</exception>
    public ProviderConfig(
        ProviderSettings settings,
        string engineId,
        string? resolvedApiKey,
        JsonObject? resolvedOptions = null)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ProviderId = settings.InstanceId;
        EngineId = ProviderSettings.NormalizeId(engineId, nameof(engineId));
        BaseUrl = settings.BaseUrl;
        ApiKey = resolvedApiKey;
        ApiVersion = settings.ApiVersion;
        Headers = new ReadOnlyDictionary<string, string>(
            settings.Headers.ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.OrdinalIgnoreCase));
        Options = resolvedOptions ?? settings.Options;
        TimeoutS = settings.TimeoutS;
        Transport = settings.Transport;
        Limits = settings.Limits;
        Proxy = settings.Proxy;
        Verify = settings.Verify;
        ClientCertificate = settings.ClientCertificate;
    }

    /// <summary>Gets the configured provider-instance identity.</summary>
    public string ProviderId { get; }
    /// <summary>Gets the resolved descriptor engine identity.</summary>
    public string EngineId { get; }
    /// <summary>Gets the resolved provider base URL.</summary>
    public string? BaseUrl { get; }
    /// <summary>Gets the resolved API secret; adapters must not log it.</summary>
    public string? ApiKey { get; }
    /// <summary>Gets the optional provider API version.</summary>
    public string? ApiVersion { get; }
    /// <summary>Gets immutable request headers.</summary>
    public IReadOnlyDictionary<string, string> Headers { get; }
    /// <summary>Gets immutable resolved setup options.</summary>
    public JsonObject? Options { get; }
    /// <summary>Gets the effective instance timeout in seconds.</summary>
    public double TimeoutS { get; }
    /// <summary>Gets the ownership-transferred transport supplied by settings.</summary>
    public HttpMessageHandler? Transport { get; }
    /// <summary>Gets optional client-side pacing limits for this configured instance.</summary>
    public RateLimits? Limits { get; }
    /// <summary>Gets optional explicit proxy settings.</summary>
    public ProviderProxy? Proxy { get; }
    /// <summary>Gets optional non-default TLS verification settings.</summary>
    public TlsVerification? Verify { get; }
    /// <summary>Gets optional PEM client-certificate settings.</summary>
    public ClientCertificate? ClientCertificate { get; }
    // Set only by an opted-in pool for a supplied handler that outlives transient adapters.
    internal bool TransportOwnedByPool { get; init; }

    internal ProviderConfig WithTransport(HttpMessageHandler transport, bool transportOwnedByPool) =>
        new(this, transport, transportOwnedByPool);

    private ProviderConfig(ProviderConfig source, HttpMessageHandler transport, bool transportOwnedByPool)
    {
        ProviderId = source.ProviderId;
        EngineId = source.EngineId;
        BaseUrl = source.BaseUrl;
        ApiKey = source.ApiKey;
        ApiVersion = source.ApiVersion;
        Headers = source.Headers;
        Options = source.Options;
        TimeoutS = source.TimeoutS;
        Limits = source.Limits;
        Proxy = source.Proxy;
        Verify = source.Verify;
        ClientCertificate = source.ClientCertificate;
        Transport = transport;
        TransportOwnedByPool = transportOwnedByPool;
    }

    /// <summary>Returns a diagnostic rendering that names only the instance and engine identities.</summary>
    /// <returns><c>ProviderConfig(instance, engine)</c>; the secret, headers, and options are never included.</returns>
    public override string ToString() => $"ProviderConfig({ProviderId}, {EngineId})";
}
