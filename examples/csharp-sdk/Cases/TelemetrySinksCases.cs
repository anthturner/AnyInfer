using System.Diagnostics;
using AnyInfer.Events;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the trace-source, JSONL, and payload opt-in telemetry recipe.</summary>
internal static class TelemetrySinksCases
{
    private const string Prompt = "Say hello.";

    /// <summary>The trace sink and JSONL trail are payload-free; only the opted-in audit observer sees text.</summary>
    [ExampleCase("telemetry-sinks.payload-opt-in")]
    internal static async Task PayloadOptIn()
    {
        var directory = Path.Combine(Path.GetTempPath(), $"anyinfer-telemetry-{Guid.NewGuid():N}");
        try
        {
            var trailPath = Path.Combine(directory, "trail", "telemetry.jsonl");
            using var writer = new StringWriter();
            var trace = TelemetrySinksExample.CreateTraceSource(writer);
            var audit = new RecipeCollectingObserver();
            var transport = new RecipeChatHandler("hello there");
            var result = await TelemetrySinksExample.RunAsync(
                ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), transport),
                ExampleSupport.Target,
                trace,
                trailPath,
                audit);
            trace.Close();

            var traced = writer.ToString();
            var trail = File.ReadAllLines(trailPath);
            ExampleSupport.Require(
                result.Text == "hello there" && transport.Requests == 1 && transport.Disposals == 1,
                "The observed generation did not complete through its transport.");
            ExampleSupport.Require(
                audit.Events.OfType<RequestStarted>().Single().PromptText == Prompt
                && audit.Events.OfType<RequestCompleted>().Single().ResponseText == "hello there",
                "The payload opt-in subscription did not receive prompt and response text.");
            ExampleSupport.Require(
                traced.Contains("\"RequestStarted\"", StringComparison.Ordinal)
                && traced.Contains("\"RequestCompleted\"", StringComparison.Ordinal)
                && !traced.Contains(Prompt, StringComparison.Ordinal)
                && !traced.Contains("hello there", StringComparison.Ordinal),
                "The trace sink was not written, or it carried payload text.");
            ExampleSupport.Require(
                trail.Length == audit.Events.Count
                && trail.Any(static line => line.Contains("\"RequestCompleted\"", StringComparison.Ordinal))
                && trail.All(static line => !line.Contains(Prompt, StringComparison.Ordinal) && !line.Contains("hello there", StringComparison.Ordinal)),
                "The JSONL trail did not record one payload-free line per event.");
            if (!OperatingSystem.IsWindows())
            {
                ExampleSupport.Require(
                    File.GetUnixFileMode(trailPath) == (UnixFileMode.UserRead | UnixFileMode.UserWrite),
                    "The JSONL trail was not created owner-read/write only.");
            }
        }
        finally
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
    }

    /// <summary>A LoggingObserver writes nothing while its trace switch is off, and writes once the switch is raised.</summary>
    [ExampleCase("telemetry-sinks.switch-off-writes-nothing")]
    internal static async Task SwitchOffWritesNothing()
    {
        using var writer = new StringWriter();
        var trace = TelemetrySinksExample.CreateTraceSource(writer, SourceLevels.Off);
        var transport = new RecipeChatHandler();
        await using (var client = new AsyncClient(
            [ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), transport)],
            observers: [new LoggingObserver(trace)]))
        {
            await client.GenerateAsync(Prompt, target: ExampleSupport.Target);
            trace.Flush();
            ExampleSupport.Require(
                writer.ToString().Length == 0 && transport.Requests == 1,
                "A LoggingObserver wrote telemetry while its trace switch was off.");

            trace.Switch.Level = SourceLevels.Information;
            await client.GenerateAsync(Prompt, target: ExampleSupport.Target);
            trace.Flush();
        }

        trace.Close();
        ExampleSupport.Require(
            writer.ToString().Contains("\"RequestCompleted\"", StringComparison.Ordinal) && transport.Requests == 2,
            "A LoggingObserver did not write telemetry once its trace switch was raised.");
    }

    /// <summary>Generation manifests carry redacted payloads only with manifestPayloads; retrieval manifests never do.</summary>
    [ExampleCase("telemetry-sinks.manifest-payload-opt-in")]
    internal static async Task ManifestPayloadOptIn()
    {
        var plain = new RecipeChatHandler("hello there");
        var plainManifest = await ManifestExample.RunAsync(
            ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), plain), ExampleSupport.Target);
        ExampleSupport.Require(
            plainManifest.Terminal.Payloads is null,
            "A manifest captured payloads without manifestPayloads.");

        var chat = new RecipeChatHandler("hello there");
        var embed = new RecipeTeiHandler();
        await using (var client = new AsyncClient(
            [
                ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), chat),
                ProviderSettings.Of("tei", "http://127.0.0.1:8080", transport: embed, alias: "tei-embed"),
            ],
            manifests: true,
            manifestPayloads: true))
        {
            var generation = await client.GenerateAsync(Prompt, target: ExampleSupport.Target);
            var embedding = await client.EmbedAsync("A river carries water.", target: "tei-embed:m");
            ExampleSupport.Require(
                generation.Manifest?.Payloads is { PromptText: Prompt, ResponseText: "hello there" }
                && embedding.Manifest is { Payloads: null },
                "manifestPayloads did not add generation payloads only.");
        }
    }

    /// <summary>An observer that throws is isolated: the request still succeeds and later observers still run.</summary>
    [ExampleCase("telemetry-sinks.failing-observer-isolated")]
    internal static async Task FailingObserverIsolated()
    {
        var transport = new RecipeChatHandler();
        var after = new RecipeCollectingObserver();
        await using (var client = new AsyncClient(
            [ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), transport)],
            observers: [new RecipeThrowingObserver(), after]))
        {
            var result = await client.GenerateAsync(Prompt, target: ExampleSupport.Target);
            ExampleSupport.Require(
                result.Text == "hello"
                && after.Events.OfType<RequestCompleted>().Count() == 1
                && after.Events.OfType<RequestStarted>().Single().PromptText is null,
                "A throwing observer failed the request or stopped later payload-free observers.");
        }
    }
}

/// <summary>Collects every event it receives.</summary>
internal sealed class RecipeCollectingObserver : IObserver
{
    private readonly List<TelemetryEvent> _events = [];

    /// <summary>Gets the events received so far.</summary>
    public IReadOnlyList<TelemetryEvent> Events
    {
        get
        {
            lock (_events)
            {
                return _events.ToArray();
            }
        }
    }

    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        lock (_events)
        {
            _events.Add(telemetryEvent);
        }
    }
}

/// <summary>Throws from every event.</summary>
internal sealed class RecipeThrowingObserver : IObserver
{
    public void OnEvent(TelemetryEvent telemetryEvent) => throw new InvalidOperationException("Offline observer failure.");
}
