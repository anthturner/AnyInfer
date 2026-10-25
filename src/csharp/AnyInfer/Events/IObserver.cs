namespace AnyInfer.Events;

/// <summary>Receives one synchronous, typed telemetry event.</summary>
/// <remarks>
/// Register an observer through the client constructors' <c>observers</c> argument or with
/// <see cref="AsyncClient.Subscribe(IObserver, bool)"/>. Events are delivered synchronously on the thread that
/// produced them, so a slow observer slows the request, and concurrent requests can call the same observer
/// concurrently. An exception thrown by an observer is caught and does not fail the request; the first one from
/// each subscription is reported as a warning trace and later ones are suppressed.
/// </remarks>
public interface IObserver
{
    /// <summary>Handles one emitted telemetry event.</summary>
    /// <param name="telemetryEvent">
    /// The event. Unless the observer was subscribed with payloads enabled, payload fields such as
    /// <see cref="RequestStarted.PromptText"/>, <see cref="RepairAttempted.RawText"/>, and
    /// <see cref="RequestCompleted.ResponseText"/> are <see langword="null"/>.
    /// </param>
    void OnEvent(TelemetryEvent telemetryEvent);
}
