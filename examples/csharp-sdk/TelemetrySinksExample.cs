using System.Diagnostics;
using AnyInfer.Events;

namespace AnyInfer.Examples;

/// <summary>
/// Sends payload-free telemetry to a trace source and a JSONL file, and gives one audit observer the
/// prompt and response text.
/// </summary>
public static class TelemetrySinksExample
{
    // --8<-- [start:trace]
    /// <summary>Creates a trace source that writes telemetry lines to a writer the application owns.</summary>
    /// <param name="writer">Where each event line is written.</param>
    /// <param name="level">
    /// The switch level. <see cref="SourceLevels.Off"/> records nothing; <see cref="SourceLevels.Information"/>
    /// records every event a <see cref="LoggingObserver"/> writes at its default level.
    /// </param>
    /// <returns>A trace source the caller flushes and closes.</returns>
    public static TraceSource CreateTraceSource(TextWriter writer, SourceLevels level = SourceLevels.Information)
    {
        var source = new TraceSource("AnyInfer.Telemetry", level);
        source.Listeners.Clear();
        source.Listeners.Add(new TextWriterTraceListener(writer));
        return source;
    }
    // --8<-- [end:trace]

    // --8<-- [start:observe]
    /// <summary>Generates one response observed by a trace sink, a JSONL trail, and a payload-bearing audit observer.</summary>
    /// <param name="settings">The provider instance to call.</param>
    /// <param name="target">A <c>provider:model</c> target.</param>
    /// <param name="trace">A trace source from <see cref="CreateTraceSource"/>.</param>
    /// <param name="trailPath">The JSONL file to append to; its directory is created when missing.</param>
    /// <param name="audit">An observer the application has decided may see prompt and response text.</param>
    /// <param name="cancellationToken">Cancels the call.</param>
    /// <returns>The buffered result.</returns>
    public static async Task<Generation> RunAsync(
        ProviderSettings settings,
        string target,
        TraceSource trace,
        string trailPath,
        IObserver audit,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(trace);
        using var trail = new JsonlObserver(trailPath);
        await using (var client = new AsyncClient([settings], observers: [new LoggingObserver(trace), trail]))
        {
            // Constructor observers are payload-free; this one subscription opts in to payloads.
            client.Subscribe(audit, payloads: true);
            var generation = await client.GenerateAsync("Say hello.", target: target, cancellationToken: cancellationToken)
                .ConfigureAwait(false);
            trace.Flush();
            return generation;
        }
    }
    // --8<-- [end:observe]
}
