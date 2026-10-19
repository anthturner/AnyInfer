using AnyInfer.Json;
using System.Collections.ObjectModel;
using System.Net.Http;

namespace AnyInfer.Providers;

/// <summary>Resolved adapter-facing configuration for one provider instance.</summary>
public sealed record ProviderConfig
{
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
    // Set only by an opted-in pool for a supplied handler that outlives transient adapters.
    internal bool TransportOwnedByPool { get; init; }

    public override string ToString() => $"ProviderConfig({ProviderId}, {EngineId})";
}
