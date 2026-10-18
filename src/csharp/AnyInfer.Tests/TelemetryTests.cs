using System.Collections.Concurrent;
using System.Diagnostics;
using AnyInfer.Events;
using AnyInfer.Json;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Pure observer, sink, redaction, and closed telemetry projection controls.</summary>
public sealed class TelemetryTests
{
    [Fact]
    public void Closed_event_family_projects_each_tag_and_preserves_money_as_a_string()
    {
        var target = new ResolvedTarget("alpha", "model");
        var usage = new Usage(CostUsd: PeterO.Numbers.EDecimal.FromString("1E-34"));
        var timing = new Timing();
        var error = new ErrorInfo("E", null, null, false, null, null);
        TelemetryEvent[] events = [
            new RequestStarted("r", ["a"]), new ArenaCompleted("r", 1, "s", null, 0, 0, false), new TargetResolved("r", target), new AttemptStarted("r", target, 1), new FirstToken("r", target, 1), new AttemptCompleted("r", target, usage, timing, "stop"), new RetryScheduled("r", target, 1, 0, error), new FallbackTriggered("r", target, "b"), new RepairAttempted("r", target, 1, null), new RequestCompleted("r", target, usage, timing), new RequestFailed("r", error), new ParameterDropped("r", target, "p", "why"), new ProviderDiagnostic(null, new Diagnostic("c", "w", "m")), new UsageEstimated("r", target, "input", "estimate"), new ContextReduced("trim", "summary", 0, 0, 0, 0, 0), new CachePlanned("r", target, "prefix", 0, 0), new RateLimitWaited("r", "alpha", 0, "quota"), new RateLimitObserved("alpha"), new ServerLifecycle("server", "ready"), new DownloadProgress("a", 0, null), new BatchSubmitted("b", target, 0), new BatchCompleted("b", target, "done", 0, 0), new CredentialRotated("alpha")];

        var tags = events.Select(EventTag).ToArray();
        Assert.Equal(23, tags.Distinct(StringComparer.Ordinal).Count());
        Assert.Contains("RequestStarted", tags);
        Assert.Contains("CredentialRotated", tags);
        var usageJson = Assert.IsType<JsonObject>(Property(Assert.IsType<JsonObject>(events[5].ToDictionary()), "usage"));
        Assert.Equal("1E-34", Assert.IsType<JsonString>(Property(usageJson, "cost_usd")).Value);
    }

    [Fact]
    public void Event_projection_recursively_redacts_secret_values_and_colliding_redacted_map_keys_last_win()
    {
        var secret = "telemetry-secret-" + Guid.NewGuid().ToString("N");
        Redaction.RegisterSecret(secret);
            var eventValue = new RequestStarted("r", [secret], [new(secret, "first"), new("[redacted]", "last")], promptText: secret);
            var json = eventValue.ToDictionary();
            var metadata = Assert.IsType<JsonObject>(Property(json, "metadata"));
            Assert.Single(metadata.Properties);
            Assert.Equal("[redacted]", metadata.Properties.Single().Name);
            Assert.Equal("last", Assert.IsType<JsonString>(metadata.Properties.Single().Value).Value);
            Assert.DoesNotContain(secret, JsonWriter.WriteManifestCanonical(json), StringComparison.Ordinal);
    }

    [Fact]
    public void Dispatcher_snapshots_subscriptions_strips_exactly_three_payload_fields_and_unsubscribes_by_reference()
    {
        var dispatcher = new EventDispatcher();
        var privateObserver = new Collector();
        var publicObserver = new Collector();
        dispatcher.Subscribe(publicObserver);
        dispatcher.Subscribe(privateObserver, payloads: true);
        Assert.True(dispatcher.HasObservers);
        Assert.True(dispatcher.WantsPayloads);

        var target = new ResolvedTarget("alpha", "model");
        dispatcher.Emit(new RequestStarted("r", ["a"], promptText: "prompt"));
        dispatcher.Emit(new RepairAttempted("r", target, 1, null, rawText: "raw"));
        dispatcher.Emit(new RequestCompleted("r", target, new Usage(), new Timing(), ResponseText: "response"));

        var publicEvents = publicObserver.Events.ToArray();
        var privateEvents = privateObserver.Events.ToArray();
        Assert.Null(Assert.IsType<RequestStarted>(publicEvents[0]).PromptText);
        Assert.Null(Assert.IsType<RepairAttempted>(publicEvents[1]).RawText);
        Assert.Null(Assert.IsType<RequestCompleted>(publicEvents[2]).ResponseText);
        Assert.Equal("prompt", Assert.IsType<RequestStarted>(privateEvents[0]).PromptText);
        Assert.Equal("raw", Assert.IsType<RepairAttempted>(privateEvents[1]).RawText);
        Assert.Equal("response", Assert.IsType<RequestCompleted>(privateEvents[2]).ResponseText);

        dispatcher.Subscribe(publicObserver);
        dispatcher.Unsubscribe(publicObserver);
        dispatcher.Emit(new ServerLifecycle("s", "ready"));
        Assert.Equal(3, publicObserver.Events.Count);
        Assert.Equal(4, privateObserver.Events.Count);
    }

    [Fact]
    public async Task Dispatcher_reentrancy_fault_isolation_and_concurrent_warn_once_are_subscription_scoped()
    {
        var secret = "observer-secret-" + Guid.NewGuid().ToString("N");
        Redaction.RegisterSecret(secret);
        var warnings = new ConcurrentQueue<string>();
        var dispatcher = new EventDispatcher(warningSink: warnings.Enqueue);
        var later = new Collector();
        var reentrant = new CallbackObserver(_ => dispatcher.Subscribe(later));
        var throwing = new CallbackObserver(_ => throw new InvalidOperationException(secret));
        dispatcher.Subscribe(reentrant);
        dispatcher.Subscribe(throwing);
        dispatcher.Subscribe(throwing);
        dispatcher.Emit(new ServerLifecycle("s", "one"));
        Assert.Empty(later.Events);
        dispatcher.Emit(new ServerLifecycle("s", "two"));
        Assert.Single(later.Events);

        var tasks = Enumerable.Range(0, 16).Select(_ => Task.Run(() => dispatcher.Emit(new ServerLifecycle("s", "concurrent"))));
        await Task.WhenAll(tasks);
        Assert.Equal(2, warnings.Count);
        Assert.All(warnings, warning => Assert.DoesNotContain(secret, warning, StringComparison.Ordinal));
    }

    [Fact]
    public void Jsonl_and_logging_sinks_are_explicit_caller_owned_and_validate_levels()
    {
        var path = Path.Combine(Path.GetTempPath(), "anyinfer-events-" + Guid.NewGuid().ToString("N") + ".jsonl");
        try
        {
            using (var jsonl = new JsonlObserver(path, flush: true))
            {
                jsonl.OnEvent(new ServerLifecycle("s", "ready"));
                jsonl.Close();
                jsonl.OnEvent(new ServerLifecycle("s", "ignored"));
            }
            Assert.Single(File.ReadAllLines(path));

            var source = new TraceSource("AnyInfer.Tests.Events") { Switch = new SourceSwitch("test") { Level = SourceLevels.All } };
            var listener = new CaptureListener();
            source.Listeners.Clear(); source.Listeners.Add(listener);
            new LoggingObserver(source, TraceEventType.Warning).OnEvent(new ServerLifecycle("s", "ready"));
            Assert.Equal(TraceEventType.Warning, listener.Type);
            Assert.Contains("ServerLifecycle", listener.Message, StringComparison.Ordinal);
            Assert.Throws<ArgumentOutOfRangeException>(() => new LoggingObserver(level: (TraceEventType)12345));
        }
        finally { if (File.Exists(path)) File.Delete(path); }
    }

    private static string EventTag(TelemetryEvent telemetryEvent) => Assert.IsType<JsonString>(Property(Assert.IsType<JsonObject>(telemetryEvent.ToDictionary()), "event")).Value;
    private static JsonValue Property(JsonObject source, string name) => source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Missing {name}.");

    private sealed class Collector : IObserver
    {
        internal ConcurrentQueue<TelemetryEvent> Events { get; } = new();
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Enqueue(telemetryEvent);
    }
    private sealed class CallbackObserver(Action<TelemetryEvent> callback) : IObserver
    {
        public void OnEvent(TelemetryEvent telemetryEvent) => callback(telemetryEvent);
    }
    private sealed class CaptureListener : TraceListener
    {
        internal TraceEventType Type { get; private set; }
        internal string Message { get; private set; } = string.Empty;
        public override void Write(string? message) { }
        public override void WriteLine(string? message) { }
        public override void TraceEvent(TraceEventCache? cache, string source, TraceEventType eventType, int id, string? message) { Type = eventType; Message = message ?? string.Empty; }
    }
}
