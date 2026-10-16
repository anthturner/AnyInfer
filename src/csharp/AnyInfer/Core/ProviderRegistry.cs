using AnyInfer.Providers;

namespace AnyInfer.Core;

internal sealed record ResolvedProvider(Target Target, ProviderRegistration Registration, StructuredOutputProfile Capabilities);

internal sealed class ProviderRegistry
{
    private readonly IReadOnlyDictionary<string, ProviderRegistration> _registrations;

    internal ProviderRegistry(IEnumerable<ProviderRegistration> registrations)
    {
        ArgumentNullException.ThrowIfNull(registrations);
        var byId = new Dictionary<string, ProviderRegistration>(StringComparer.Ordinal);
        var adapters = new List<IProviderAdapter>();
        var distinctAdapters = new HashSet<IProviderAdapter>(ReferenceEqualityComparer.Instance);
        foreach (var registration in registrations)
        {
            ArgumentNullException.ThrowIfNull(registration);
            if (!byId.TryAdd(registration.ProviderId, registration))
            {
                throw new ArgumentException("Provider registrations must have unique provider IDs.", nameof(registrations));
            }

            if (distinctAdapters.Add(registration.Adapter))
            {
                adapters.Add(registration.Adapter);
            }
        }

        _registrations = byId;
        Adapters = Array.AsReadOnly(adapters.ToArray());
    }

    internal IReadOnlyList<IProviderAdapter> Adapters { get; }

    internal ResolvedProvider Resolve(string rawTarget)
    {
        ArgumentNullException.ThrowIfNull(rawTarget);
        if (string.IsNullOrWhiteSpace(rawTarget))
        {
            throw ConfigureError("Target is empty.");
        }

        var separator = rawTarget.IndexOf(':');
        if (separator < 0)
        {
            throw new ProviderException(
                "Target aliases are outside the core-generation v0 profile.",
                "unsupported_input",
                retryable: false,
                phase: "generate",
                detail: "The target does not include a provider and model.",
                hint: "Use a provider:model target.");
        }

        var providerId = rawTarget[..separator];
        var model = rawTarget[(separator + 1)..].Trim();
        if (providerId.Length == 0 || model.Length == 0)
        {
            throw ConfigureError("Target provider or model is empty.");
        }

        if (!_registrations.TryGetValue(providerId, out var registration))
        {
            throw ConfigureError("Target provider is not registered.");
        }

        var capabilities = registration.ModelCapabilities.TryGetValue(model, out var profile)
            ? profile
            : new StructuredOutputProfile();
        return new ResolvedProvider(new Target(providerId, model), registration, capabilities);
    }

    private static ProviderException ConfigureError(string detail) =>
        new(
            "The target cannot be configured.",
            "invalid_request",
            retryable: false,
            phase: "configure",
            detail: detail,
            hint: "Use a registered provider:model target.");
}
