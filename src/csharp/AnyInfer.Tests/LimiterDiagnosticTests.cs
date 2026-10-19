using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public generation controls for unsupported rate-limit header diagnostics.</summary>
public sealed class LimiterDiagnosticTests
{
    [Fact]
    public async Task Active_unsupported_header_dialect_emits_one_diagnostic_after_attempt_start()
    {
        var observer = new Collector();
        await using var client = CreateClient(
            "unsupported",
            new ScriptedAdapter(static (_, token) => Success(token)),
            new RateLimits(minIntervalS: 1),
            observer);

        await client.GenerateAsync("request", target: "unsupported:model");

        var dropped = Assert.Single(observer.Events.OfType<ParameterDropped>());
        Assert.Equal("limits.respect_headers", dropped.Parameter);
        Assert.Equal("this provider publishes no rate-limit headers", dropped.Reason);
        var attempt = Assert.Single(observer.Events.OfType<AttemptStarted>());
        Assert.True(observer.Events.IndexOf(attempt) < observer.Events.IndexOf(dropped));
        Assert.True(observer.Events.IndexOf(dropped) < observer.Events.FindIndex(static item => item is AttemptCompleted));
    }

    [Fact]
    public async Task Declared_headers_or_disabled_header_respect_are_silent()
    {
        var declaredObserver = new Collector();
        var declared = new ProviderDescriptor(
            "declared",
            "declared",
            (_, _) => ValueTask.FromResult<IProviderAdapter>(new ScriptedAdapter(static (_, token) => Success(token))),
            rateLimitHeaders: new RateLimitHeaders(requestsRemaining: "x-remaining", requestsReset: "x-reset"));
        await using var declaredClient = new AsyncClient(
            [ProviderSettings.Of("declared", limits: new RateLimits(minIntervalS: 1))],
            new ProviderRegistry([declared]),
            observers: [declaredObserver]);
        await declaredClient.GenerateAsync("request", target: "declared:model");
        Assert.DoesNotContain(declaredObserver.Events, static item => item is ParameterDropped { Parameter: "limits.respect_headers" });

        var disabledObserver = new Collector();
        await using var disabledClient = CreateClient(
            "disabled",
            new ScriptedAdapter(static (_, token) => Success(token)),
            new RateLimits(minIntervalS: 1, respectHeaders: false),
            disabledObserver);
        await disabledClient.GenerateAsync("request", target: "disabled:model");
        Assert.DoesNotContain(disabledObserver.Events, static item => item is ParameterDropped { Parameter: "limits.respect_headers" });
    }

    [Fact]
    public async Task Unsupported_header_diagnostic_is_emitted_once_for_each_outer_retry_attempt()
    {
        var observer = new Collector();
        var retryable = new ProviderException("retry", "transport", true, "generate");
        await using var client = CreateClient(
            "retry",
            new ScriptedAdapter((call, token) => call == 1
                ? Throw(token, retryable)
                : Success(token)),
            new RateLimits(minIntervalS: 1),
            observer);

        var result = await client.GenerateAsync(new GenerationRequest(
            [Message.User("request")],
            new Route(["retry:model"], new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 0))));

        Assert.Equal("ok", result.Text);
        var indexedEvents = observer.Events
            .Select(static (item, position) => (Item: item, Position: position))
            .ToArray();
        var attempts = indexedEvents.Where(static item => item.Item is AttemptStarted).ToArray();
        var drops = indexedEvents
            .Where(static item => item.Item is ParameterDropped { Parameter: "limits.respect_headers" })
            .ToArray();
        var terminal = Assert.Single(indexedEvents, static item => item.Item is AttemptCompleted);
        Assert.Equal(2, attempts.Length);
        Assert.Equal(attempts.Length, drops.Length);
        for (var index = 0; index < attempts.Length; index++)
        {
            var intervalEnd = index + 1 < attempts.Length ? attempts[index + 1].Position : terminal.Position;
            Assert.InRange(drops[index].Position, attempts[index].Position + 1, intervalEnd - 1);
        }
    }

    [Fact]
    public async Task Unsupported_header_diagnostic_is_not_repeated_for_schema_repair_entries()
    {
        var observer = new Collector();
        await using var client = CreateClient(
            "repair",
            new ScriptedAdapter((call, token) => call == 1
                ? Events(token, new AdapterTextDelta("\"wrong\""), new AdapterFinal("stop"))
                : Events(token, new AdapterTextDelta("\"correct\""), new AdapterFinal("stop"))),
            new RateLimits(minIntervalS: 1),
            observer);

        var result = await client.GenerateAsync(
            "request",
            target: "repair:model",
            schema: new SchemaSpec(JsonReader.Read("{\"const\":\"correct\"}")),
            repair: new Repair(1));

        Assert.Equal(1, result.RepairAttempts);
        Assert.Single(observer.Events.OfType<ParameterDropped>());
    }

    private static AsyncClient CreateClient(
        string id,
        IProviderAdapter adapter,
        RateLimits limits,
        IObserver observer)
    {
        var descriptor = new ProviderDescriptor(
            id,
            id,
            (_, _) => ValueTask.FromResult(adapter));
        return new AsyncClient(
            [ProviderSettings.Of(id, limits: limits)],
            new ProviderRegistry([descriptor]),
            observers: [observer]);
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private sealed class ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        private int _calls;

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default) =>
            script(++_calls, cancellationToken);

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private static async IAsyncEnumerable<AdapterEvent> Success([EnumeratorCancellation] CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta("ok");
        yield return new AdapterFinal("stop");
        await Task.Yield();
    }

    private static async IAsyncEnumerable<AdapterEvent> Events(
        [EnumeratorCancellation] CancellationToken cancellationToken,
        params AdapterEvent[] events)
    {
        foreach (var adapterEvent in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return adapterEvent;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(
        [EnumeratorCancellation] CancellationToken cancellationToken,
        Exception error)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.Yield();
        yield return await Task.FromException<AdapterEvent>(error);
    }
}
