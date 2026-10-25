using AnyInfer.Events;

namespace AnyInfer.Examples;

/// <summary>Observes one public generation through an in-memory, payload-free observer.</summary>
public static class TelemetryExample
{
    /// <summary>Generates one response and returns the immutable event observations collected inline.</summary>
    public static async Task<TelemetryObservation> RunAsync(
        ProviderSettings settings,
        string target,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(target);

        var observer = new CollectingObserver();
        await using var client = new AsyncClient([settings], manifests: true, manifestPayloads: false);
        client.Subscribe(observer);
        try
        {
            var generation = await client.GenerateAsync(
                "Say hello.",
                target: target,
                cancellationToken: cancellationToken);
            return new TelemetryObservation(generation, observer.Snapshot());
        }
        finally
        {
            client.Unsubscribe(observer);
        }
    }

    private sealed class CollectingObserver : IObserver
    {
        private readonly List<TelemetryEvent> _events = [];

        public void OnEvent(TelemetryEvent telemetryEvent) => _events.Add(telemetryEvent);

        public IReadOnlyList<TelemetryEvent> Snapshot() => Array.AsReadOnly(_events.ToArray());
    }
}

/// <summary>Contains one terminal result and the payload-free events observed for it.</summary>
public sealed record TelemetryObservation(Generation Generation, IReadOnlyList<TelemetryEvent> Events);
