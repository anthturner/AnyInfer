using System.Net;
using System.Net.Http;
using System.Runtime.CompilerServices;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public provider settings, descriptor, and lazy instance-pool behavior.</summary>
public sealed class ProviderSettingsTests
{
    [Fact]
    public void Settings_canonicalize_instance_identity_and_copy_safe_values()
    {
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["X-Mode"] = "original" };
        var options = Assert.IsType<JsonObject>(JsonReader.Read("{\"region\":\"one\"}"));

        var settings = ProviderSettings.Of("  Fake_Engine  ", headers: headers, options: options, alias: " Tenant_A ");
        headers["X-Mode"] = "mutated";

        Assert.Equal("fake-engine", settings.ProviderId);
        Assert.Equal("tenant-a", settings.Alias);
        Assert.Equal("tenant-a", settings.InstanceId);
        Assert.Equal("original", settings.Headers["X-Mode"]);
        Assert.Same(options, settings.Options);
        Assert.Equal(JsonWriter.Write(options), JsonWriter.Write(settings.Options!));
    }

    [Fact]
    public void Registry_and_configured_instances_reject_canonical_collisions_before_factory_or_disposal()
    {
        var first = Descriptor("fake_engine", aliases: ["fake"]);
        var registry = new ProviderRegistry([first]);
        Assert.Throws<ArgumentException>(() => registry.Register(Descriptor("other", aliases: ["Fake_Engine"])));

        var handler = new TrackingHandler();
        var settings = new[]
        {
            ProviderSettings.Of("fake-engine", alias: "Work_A", transport: handler),
            ProviderSettings.Of("fake-engine", alias: "work-a", transport: new TrackingHandler()),
        };
        Assert.Throws<ConfigException>(() => new AsyncClient(settings, registry));
        Assert.Equal(0, handler.DisposeCalls);
    }

    [Fact]
    public void Same_transport_handler_cannot_be_reused_by_two_instances_before_client_lifetime_adoption()
    {
        var handler = new TrackingHandler();
        var registry = new ProviderRegistry([Descriptor("fake-engine")]);
        var settings = new[]
        {
            ProviderSettings.Of("fake-engine", alias: "one", transport: handler),
            ProviderSettings.Of("fake-engine", alias: "two", transport: handler),
        };

        Assert.Throws<ConfigException>(() => new AsyncClient(settings, registry));
        Assert.Equal(0, handler.DisposeCalls);
    }

    [Fact]
    public async Task Configured_alias_binding_is_lazy_and_uses_per_instance_defaults()
    {
        var calls = new List<ProviderConfig>();
        var adapter = new RecordingAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "fake-engine",
                "Fake",
                (config, _) =>
                {
                    calls.Add(config);
                    return ValueTask.FromResult<IAsyncDisposable>(adapter);
                },
                defaultBaseUrl: "https://descriptor.example")]);
        var settings = ProviderSettings.Of("FAKE_ENGINE", timeoutS: 17.5, alias: "Tenant_A");
        await using var client = new AsyncClient([settings], registry, route: new Route(["tenant-a:model"]));

        var stream = client.StreamAsync("lazy");
        Assert.Empty(calls);
        Assert.Equal(0, adapter.GenerateCalls);

        var result = await stream.CollectAsync();

        var bound = Assert.Single(calls);
        Assert.Equal("tenant-a", bound.ProviderId);
        Assert.Equal("fake-engine", bound.EngineId);
        Assert.Equal("https://descriptor.example", bound.BaseUrl);
        Assert.Equal(17.5, bound.TimeoutS);
        Assert.Equal("tenant-a", result.Target!.ProviderId);
        Assert.Null(result.Target.ViaAlias);
        Assert.Equal(1, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Default_url_binding_copies_connection_values_without_materializing_them_before_iteration()
    {
        var calls = new List<ProviderConfig>();
        var adapter = new RecordingAdapter();
        var proxy = ProviderProxy.Parse("https://proxy-user:proxy-password@proxy.invalid:443/");
        var verification = TlsVerification.FromPemBundle("not-loaded-before-factory.pem");
        var certificate = ClientCertificate.FromPemFile("also-not-loaded-before-factory.pem");
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "fake-engine",
                "Fake",
                (config, _) =>
                {
                    calls.Add(config);
                    return ValueTask.FromResult<IAsyncDisposable>(adapter);
                },
                defaultBaseUrl: "https://descriptor.example/v1"),
        ]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("fake-engine", alias: "tenant", proxy: proxy, verify: verification, clientCertificate: certificate)],
            registry,
            route: new Route(["tenant:model"]));

        var stream = client.StreamAsync("lazy");
        Assert.Empty(calls);
        Assert.Equal(0, adapter.GenerateCalls);

        await stream.CollectAsync();

        var bound = Assert.Single(calls);
        Assert.Equal("https://descriptor.example/v1", bound.BaseUrl);
        Assert.Same(proxy, bound.Proxy);
        Assert.Same(verification, bound.Verify);
        Assert.Same(certificate, bound.ClientCertificate);
    }

    [Fact]
    public async Task Unadvanced_post_close_streams_keep_collect_and_result_in_the_unready_state_while_manual_enumeration_is_empty()
    {
        var adapter = new RecordingAdapter();
        var client = AsyncClient.FromAdapters([new ProviderRegistration("fake", adapter)]);
        var collect = client.StreamAsync("collect", target: "fake:model");
        var manual = client.StreamAsync("manual", target: "fake:model");
        var result = client.StreamAsync("result", target: "fake:model");

        await client.DisposeAsync();

        await Assert.ThrowsAsync<InvalidOperationException>(() => collect.CollectAsync());

        await using (var enumerator = manual.GetAsyncEnumerator())
        {
            Assert.False(await enumerator.MoveNextAsync());
        }

        Assert.Throws<InvalidOperationException>(() => _ = result.Result);
        Assert.Equal(0, adapter.GenerateCalls);
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Concurrent_waiter_cancellation_does_not_cancel_the_single_owner_factory()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        var adapter = new RecordingAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", async (_, token) =>
            {
                Interlocked.Increment(ref calls);
                entered.TrySetResult();
                await release.Task.WaitAsync(token);
                return adapter;
            })]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));

        var owner = client.StreamAsync("owner").CollectAsync();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        var waiter = client.StreamAsync("waiter", cancellationToken: cancelled.Token).CollectAsync(cancelled.Token);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => waiter);
        release.TrySetResult();
        Assert.Equal("ok", (await owner).Text);
        Assert.Equal(1, calls);
        Assert.Equal(1, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Cancelled_owner_releases_the_instance_gate_for_a_waiter_without_caching_failure()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        var adapter = new RecordingAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", async (_, token) =>
            {
                var call = Interlocked.Increment(ref calls);
                if (call == 1)
                {
                    entered.TrySetResult();
                    await Task.Delay(Timeout.InfiniteTimeSpan, token);
                }

                return adapter;
            })]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));

        using var ownerCancellation = new CancellationTokenSource();
        var owner = client.StreamAsync("owner", cancellationToken: ownerCancellation.Token).CollectAsync(ownerCancellation.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var waiter = client.StreamAsync("waiter").CollectAsync();
        ownerCancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner);
        Assert.Equal("ok", (await waiter).Text);
        Assert.Equal(2, calls);
        Assert.Equal(1, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Client_disposal_closes_a_late_factory_return_once()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new RecordingAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", async (_, _) =>
            {
                entered.TrySetResult();
                await release.Task;
                return adapter;
            })]);
        var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));
        var pending = client.StreamAsync("late").CollectAsync();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));

        var disposal = client.DisposeAsync().AsTask();
        release.TrySetResult();
        await disposal;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Caller_cancellation_of_a_late_factory_return_disposes_it_without_caching()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        var discarded = new RecordingAdapter();
        var retained = new RecordingAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", async (_, _) =>
            {
                if (Interlocked.Increment(ref calls) == 1)
                {
                    entered.TrySetResult();
                    await release.Task;
                    return discarded;
                }

                return retained;
            })]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: new Route(["fake:model"]));
        using var cancellation = new CancellationTokenSource();
        var cancelled = client.StreamAsync("cancelled", cancellationToken: cancellation.Token).CollectAsync(cancellation.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        cancellation.Cancel();
        release.TrySetResult();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelled);
        Assert.Equal(1, discarded.DisposeCalls);
        Assert.Equal(0, discarded.GenerateCalls);
        Assert.Equal("ok", (await client.StreamAsync("fresh").CollectAsync()).Text);
        Assert.Equal(2, calls);
        Assert.Equal(1, retained.GenerateCalls);
    }

    [Fact]
    public async Task Target_only_call_inherits_default_retry_while_explicit_route_overrides_it()
    {
        var retryable = new TransportException("retry", retryable: true, phase: "generate");
        var inherited = new ScriptedAdapter((call, token) => call < 3
            ? Fail(retryable)
            : Events(token, new AdapterTextDelta("third"), new AdapterFinal("stop")));
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(inherited))]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("fake")],
            registry,
            route: new Route(["fake:model"], new Retry(3, 0, 0), healthGate: false));

        Assert.Equal("third", (await client.GenerateAsync("retry", target: "fake:model")).Text);
        Assert.Equal(3, inherited.GenerateCalls);

        var explicitRoute = new ScriptedAdapter((_, _) => Fail(retryable));
        var explicitRegistry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(explicitRoute))]);
        await using var explicitClient = new AsyncClient(
            [ProviderSettings.Of("fake")],
            explicitRegistry,
            route: new Route(["fake:model"], new Retry(3, 0, 0), healthGate: false));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() =>
            explicitClient.GenerateAsync("override", target: "fake:model", route: new Route(["fake:model"], new Retry(1, 0, 0), healthGate: false)));
        Assert.Equal(1, explicitRoute.GenerateCalls);
    }

    [Fact]
    public async Task Target_only_health_gate_false_does_not_skip_a_marked_target()
    {
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Fail(new TransportException("first", retryable: false, phase: "generate"))
            : Events(token, new AdapterTextDelta("second"), new AdapterFinal("stop")));
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter))]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("fake")], registry,
            route: new Route(["fake:model"], new Retry(1, 0, 0), healthGate: false));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("first", target: "fake:model"));
        Assert.Equal("second", (await client.GenerateAsync("second", target: "fake:model")).Text);
        Assert.Equal(2, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Zero_ttl_health_gate_allows_the_immediate_target_only_retry_after_failure()
    {
        var adapter = new ScriptedAdapter((call, token) => call == 1
            ? Fail(new TransportException("first", retryable: false, phase: "generate"))
            : Events(token, new AdapterTextDelta("second"), new AdapterFinal("stop")));
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter))]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("fake")], registry,
            route: new Route(["fake:model"], new Retry(1, 0, 0), healthGate: true, healthTtlS: 0));

        await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync("first", target: "fake:model"));
        Assert.Equal("second", (await client.GenerateAsync("second", target: "fake:model")).Text);
        Assert.Equal(2, adapter.GenerateCalls);
    }

    [Fact]
    public async Task Typed_request_inherits_default_repair_and_explicit_zero_disables_it()
    {
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        var repairing = new ScriptedAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("{\"age\":\"wrong\"}"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"age\":7}"), new AdapterFinal("stop")));
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(repairing))]);
        var route = new Route(["fake:model"]);
        await using var client = new AsyncClient([ProviderSettings.Of("fake")], registry, route: route, repair: new Repair(1));

        var inherited = await client.GenerateAsync(new GenerationRequest([Message.User("repair")], route, schema: schema));
        Assert.Equal("{\"age\":7}", inherited.Text);
        Assert.Equal(1, inherited.RepairAttempts);
        Assert.Equal(2, repairing.GenerateCalls);

        var noRepair = new ScriptedAdapter((_, token) => Events(token, new AdapterTextDelta("{\"age\":\"wrong\"}"), new AdapterFinal("stop")));
        var noRepairRegistry = new ProviderRegistry([
            new ProviderDescriptor("fake", "Fake", (_, _) => ValueTask.FromResult<IAsyncDisposable>(noRepair))]);
        await using var noRepairClient = new AsyncClient([ProviderSettings.Of("fake")], noRepairRegistry, route: route, repair: new Repair(1));

        await Assert.ThrowsAsync<SchemaViolationException>(() =>
            noRepairClient.GenerateAsync(new GenerationRequest([Message.User("repair")], route, repair: new Repair(0), schema: schema)));
        Assert.Equal(1, noRepair.GenerateCalls);
    }

    private static ProviderDescriptor Descriptor(string id, IEnumerable<string>? aliases = null) =>
        new(id, id, static (_, _) => ValueTask.FromResult<IAsyncDisposable>(new RecordingAdapter()), aliases: aliases);

    private sealed class RecordingAdapter : IProviderAdapter
    {
        internal int GenerateCalls { get; private set; }
        internal int DisposeCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            yield return new AdapterTextDelta("ok");
            await Task.Yield();
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterFinal("stop");
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class ScriptedAdapter : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script;

        internal ScriptedAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) => _script = script;

        internal int GenerateCalls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            var call = ++GenerateCalls;
            await foreach (var item in _script(call, cancellationToken).WithCancellation(cancellationToken))
            {
                yield return item;
            }
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken cancellationToken, params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Fail(AnyInferException failure)
    {
        if (failure is null)
        {
            yield break;
        }

        await Task.Yield();
        throw failure;
    }

    private sealed class TrackingHandler : HttpMessageHandler
    {
        internal int DisposeCalls { get; private set; }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                DisposeCalls++;
            }

            base.Dispose(disposing);
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("The handler must not dispatch during provider-pool construction tests.");
    }
}
