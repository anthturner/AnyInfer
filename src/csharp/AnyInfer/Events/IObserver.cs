namespace AnyInfer.Events;

/// <summary>Receives one synchronous, typed telemetry event.</summary>
public interface IObserver
{
    /// <summary>Handles one emitted telemetry event.</summary>
    void OnEvent(TelemetryEvent telemetryEvent);
}
