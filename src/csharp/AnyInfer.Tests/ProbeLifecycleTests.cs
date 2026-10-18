using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

using Catalog = global::AnyInfer.Catalog.Catalog;

/// <summary>Public lifecycle behavior for direct generation capability probes.</summary>
public sealed class ProbeLifecycleTests
{
    [Fact]
    public async Task Default_probe_uses_the_full_ordered_selection_direct_raw_wires_and_later_usage_overlay()
    {
        var adapter = new ProbeAdapter((request, _) => request.Mechanism switch
        {
            "json_schema" => Events(new AdapterTextDelta("{\"colour\":\"blue\"}"), new AdapterFinal("stop", new Usage(InputTokens: 1))),
            "json_mode" => Events(new AdapterTextDelta("[]"), new AdapterFinal("stop", new Usage(OutputTokens: 2))),
            _ when request.Tools.Count > 0 => Events(new AdapterToolCallDelta(0, "call", "record_colour", "{\"colour\":\"blue\"}"), new AdapterFinal("tool_calls", new Usage(TotalTokens: 3))),
            _ when request.Stream => Events(new AdapterTextDelta("one"), new AdapterTextDelta("two"), new AdapterFinal("stop", new Usage(InputTokens: 4))),
            _ => throw new Xunit.Sdk.XunitException("Unexpected probe request."),
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var report = await client.ProbeAsync("primary:model");

        Assert.Equal([Feature.JsonSchema, Feature.JsonMode, Feature.Tools, Feature.Streaming], report.Probes.Select(static probe => probe.Feature));
        Assert.All(report.Probes, static probe => Assert.Equal(ProbeOutcome.Supported, probe.Outcome));
        Assert.Equal(4, report.Requests);
        Assert.Equal(4, report.Usage.InputTokens);
        Assert.Equal(2, report.Usage.OutputTokens);
        Assert.Equal(3, report.Usage.TotalTokens);
        Assert.Equal(4, adapter.Requests.Count);
        Assert.Collection(adapter.Requests,
            request => { Assert.Equal("json_schema", request.Mechanism); Assert.False(request.Stream); Assert.Empty(request.Tools); Assert.Equal(64, request.Sampling.MaxOutputTokens); Assert.Equal(0d, request.Sampling.Temperature); },
            request => { Assert.Equal("json_mode", request.Mechanism); Assert.False(request.Stream); Assert.Empty(request.Tools); },
            request => { Assert.Null(request.Mechanism); Assert.False(request.Stream); Assert.Single(request.Tools); Assert.Equal("required", request.ToolChoice); },
            request => { Assert.Null(request.Mechanism); Assert.True(request.Stream); Assert.Empty(request.Tools); });
        Assert.NotNull(report.Capabilities);
        Assert.Equal(Provenance.Probed, report.Capabilities.Features.Provenance);
        Assert.Equal(Feature.JsonSchema | Feature.JsonMode | Feature.Tools | Feature.Streaming, report.Capabilities.Features.Value);
    }

    [Fact]
    public async Task Empty_and_duplicate_selections_preserve_actual_order_and_record_false_does_not_persist()
    {
        var adapter = new ProbeAdapter((request, _) => Events(new AdapterTextDelta("[]"), new AdapterFinal("stop", new Usage(OutputTokens: 1))));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var empty = await client.ProbeAsync("primary:model", []);
        Assert.Empty(empty.Probes);
        Assert.Equal(0, empty.Requests);
        Assert.Null(empty.Capabilities);
        Assert.Empty(adapter.Requests);

        var duplicate = await client.ProbeAsync("primary:model", [Feature.JsonMode, Feature.JsonMode], record: false);
        Assert.Equal([Feature.JsonMode, Feature.JsonMode], duplicate.Probes.Select(static probe => probe.Feature));
        Assert.Equal(2, duplicate.Requests);
        Assert.NotNull(duplicate.Capabilities);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.All(adapter.Requests, static request => Assert.Equal("json_mode", request.Mechanism));

        var persisted = client.Capabilities("primary:model");
        Assert.Equal(Feature.None, persisted.Features.Value);
        Assert.Equal(Provenance.Default, persisted.Features.Provenance);
    }

    [Fact]
    public async Task Empty_selection_resolves_and_acquires_a_configured_adapter_once_but_never_generates()
    {
        var adapter = new ProbeAdapter((_, _) => Events(new AdapterFinal("stop")));
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("primary", "Primary", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IProviderAdapter>(adapter);
            }),
        ]);
        var client = new AsyncClient([ProviderSettings.Of("primary")], registry);

        var report = await client.ProbeAsync("primary:model", []);

        Assert.Empty(report.Probes);
        Assert.Equal(0, report.Requests);
        Assert.Equal(1, factoryCalls);
        Assert.Empty(adapter.Requests);
        await client.DisposeAsync();
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Explicit_grammar_probe_forces_grammar_schema_and_prompt_and_judges_a_conforming_answer()
    {
        var adapter = new ProbeAdapter((request, _) => Events(new AdapterTextDelta("{\"colour\":\"blue\"}"), new AdapterFinal("stop")));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var report = await client.ProbeAsync("primary:model", [Feature.Grammar]);

        var request = Assert.Single(adapter.Requests);
        Assert.Equal("grammar", request.Mechanism);
        Assert.NotNull(request.Schema);
        var probeSchema = Assert.IsType<JsonObject>(request.Schema);
        Assert.True(probeSchema.TryGetValue("title", out var title));
        Assert.Equal("capability_probe", Assert.IsType<JsonString>(title).Value);
        Assert.Equal(CapabilityProbes.ProbePrompt(Feature.Grammar), Assert.IsType<Text>(Assert.Single(request.Messages).Content.Single()).Value);
        Assert.Equal(ProbeOutcome.Supported, Assert.Single(report.Probes).Outcome);
        Assert.Equal(Feature.Grammar, report.Capabilities!.Features.Value);
    }

    [Fact]
    public async Task Invalid_selection_and_non_generation_registration_refuse_before_adapter_generation()
    {
        var adapter = new ProbeAdapter((_, _) => Events(new AdapterFinal("stop")));
        await using (var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]))
        {
            await Assert.ThrowsAsync<ConfigException>(() => client.ProbeAsync("primary:model", [Feature.CacheUsage]));
            Assert.Empty(adapter.Requests);
        }

        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("embedding-only", "Embedding only", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IProviderAdapter>(adapter);
            }, operations: [InferenceOperation.Embedding]),
        ]);
        await using var nonGeneration = new AsyncClient([ProviderSettings.Of("embedding-only")], registry);
        var failure = await Assert.ThrowsAsync<ConfigException>(() => nonGeneration.ProbeAsync("embedding-only:model", [Feature.JsonMode]));
        Assert.Equal("embedding-only", failure.Provider);
        Assert.Equal(0, factoryCalls);
        Assert.Empty(adapter.Requests);
    }

    [Fact]
    public async Task Provider_exception_becomes_unsupported_but_source_cancellation_identity_escapes_without_publication()
    {
        var provider = new ProbeAdapter((_, _) => ThrowEvents(ProviderException.Create("rejected", "unsupported_input", retryable: false, phase: "generate", provider: "primary")));
        await using (var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", provider)]))
        {
            var report = await client.ProbeAsync("primary:model", [Feature.JsonMode]);
            Assert.Equal(ProbeOutcome.Unsupported, Assert.Single(report.Probes).Outcome);
            Assert.NotNull(report.Capabilities);
            Assert.Equal(Feature.None, report.Capabilities.Features.Value);
            Assert.Equal(Provenance.Probed, report.Capabilities.Features.Provenance);
        }

        using var cancellation = new CancellationTokenSource();
        var sentinel = new OperationCanceledException("source", null, cancellation.Token);
        var source = new ProbeAdapter((_, _) => ThrowEvents(sentinel));
        await using var sourceClient = AsyncClient.FromAdapters([new ProviderRegistration("primary", source)]);
        var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => sourceClient.ProbeAsync("primary:model", [Feature.JsonMode]));
        Assert.Same(sentinel, observed);
        Assert.Equal(Feature.None, sourceClient.Capabilities("primary:model").Features.Value);
        Assert.Equal(Provenance.Default, sourceClient.Capabilities("primary:model").Features.Provenance);
    }

    [Fact]
    public async Task Probe_usage_overlays_across_features_then_normalizes_once_after_the_final_overlay()
    {
        var call = 0;
        var adapter = new ProbeAdapter((_, _) => ++call switch
        {
            1 => Events(new AdapterTextDelta("[]"), new AdapterFinal("stop", new Usage(InputTokens: 2, OutputTokens: 3))),
            2 => Events(new AdapterTextDelta("{\"colour\":\"blue\"}"), new AdapterFinal("stop", new Usage(InputTokens: 7))),
            _ => throw new Xunit.Sdk.XunitException("Unexpected probe call."),
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var report = await client.ProbeAsync("primary:model", [Feature.JsonMode, Feature.Grammar]);

        Assert.Equal(7, report.Usage.InputTokens);
        Assert.Equal(3, report.Usage.OutputTokens);
        Assert.Equal(10, report.Usage.TotalTokens);
    }

    [Fact]
    public async Task Provider_failure_after_the_owned_timer_is_suppressed_remains_unsupported_and_iterator_cleanup_finishes()
    {
        var cleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ProbeAdapter((_, token) => TimeoutThenProviderFailure(token, cleaned));
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var report = await client.ProbeAsync("primary:model", [Feature.JsonMode], timeoutS: 0.02);

        await cleaned.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var probe = Assert.Single(report.Probes);
        Assert.Equal(ProbeOutcome.Unsupported, probe.Outcome);
        Assert.Equal(Feature.None, report.Capabilities!.Features.Value);
    }

    [Fact]
    public async Task Owned_timeout_is_inconclusive_but_custom_adapter_cancellation_identity_is_preserved_and_closes_iterators()
    {
        var timeoutEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var timeoutCleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var timeoutWasCancelledAtEntry = 0;
        var timeoutAdapter = new ProbeAdapter((_, token) => BlockingEvents(token, timeoutEntered, timeoutCleaned, cancelled => Volatile.Write(ref timeoutWasCancelledAtEntry, cancelled ? 1 : 0)));
        await using (var timeoutClient = AsyncClient.FromAdapters([new ProviderRegistration("primary", timeoutAdapter)]))
        {
            var pendingTimeout = timeoutClient.ProbeAsync("primary:model", [Feature.JsonMode], timeoutS: 0.02);
            await timeoutEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.Equal(0, Volatile.Read(ref timeoutWasCancelledAtEntry));
            var timed = await pendingTimeout;
            await timeoutCleaned.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.Equal(ProbeOutcome.Inconclusive, Assert.Single(timed.Probes).Outcome);
            Assert.Null(timed.Capabilities);
        }

        var callerEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callerCleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        CancellationToken deliveredFeatureToken = default;
        OperationCanceledException? adapterCancellation = null;
        var callerAdapter = new ProbeAdapter((_, token) => BlockingEvents(
            token,
            callerEntered,
            callerCleaned,
            cancellationAtEntry: null,
            tokenAtEntry: captured => deliveredFeatureToken = captured,
            captureCancellation: captured => adapterCancellation = captured));
        await using var callerClient = AsyncClient.FromAdapters([new ProviderRegistration("primary", callerAdapter)]);
        using var cancellation = new CancellationTokenSource();
        var pending = callerClient.ProbeAsync("primary:model", [Feature.JsonMode], cancellationToken: cancellation.Token);
        await callerEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        cancellation.Cancel();
        var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Same(Assert.IsAssignableFrom<OperationCanceledException>(adapterCancellation), observed);
        Assert.Equal(deliveredFeatureToken, observed.CancellationToken);
        await callerCleaned.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.Equal(Feature.None, callerClient.Capabilities("primary:model").Features.Value);
    }

    [Fact]
    public async Task Close_and_caller_cancellation_discard_token_ignoring_late_success_before_report_or_probe_publication()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ProbeAdapter((_, _) => IgnoringCancellationSuccess(entered, release));
        var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);
        using var cancellation = new CancellationTokenSource();
        var pending = client.ProbeAsync("primary:model", [Feature.JsonMode], cancellationToken: cancellation.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        cancellation.Cancel();
        release.TrySetResult();
        var observed = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.Equal(cancellation.Token, observed.CancellationToken);
        Assert.Equal(Feature.None, client.Capabilities("primary:model").Features.Value);
        await client.DisposeAsync();
        Assert.Equal(1, adapter.DisposeCalls);

        var closeEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var closeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var closeAdapter = new ProbeAdapter((_, _) => IgnoringCancellationSuccess(closeEntered, closeRelease));
        var closeClient = AsyncClient.FromAdapters([new ProviderRegistration("primary", closeAdapter)]);
        var closingProbe = closeClient.ProbeAsync("primary:model", [Feature.JsonMode]);
        await closeEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var close = closeClient.DisposeAsync().AsTask();
        closeRelease.TrySetResult();
        await close;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => closingProbe);
        Assert.Equal(1, closeAdapter.DisposeCalls);
    }

    [Fact]
    public async Task Measured_probe_snapshot_includes_untested_configured_override_bits_while_normal_assembly_keeps_override_outermost()
    {
        var adapter = new ProbeAdapter((_, _) => Events(new AdapterTextDelta("[]"), new AdapterFinal("stop")));
        var factoryCalls = 0;
        var catalog = new Catalog(aliases: new Dictionary<string, AliasEntry>
        {
            ["tier"] = new AliasEntry("tier", targets: new Dictionary<string, TargetEntry>
            {
                ["primary"] = new TargetEntry("primary", "model"),
            }),
        });
        var registry = new ProviderRegistry([
            new ProviderDescriptor("engine", "Engine", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IProviderAdapter>(adapter);
            }),
        ]);
        var overrides = new Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>>
        {
            ["primary"] = new Dictionary<string, ModelCapabilities>
            {
                ["model"] = new ModelCapabilities(features: new Sourced<Feature>(Feature.Streaming, Provenance.Override)),
            },
        };
        await using var client = new AsyncClient(
            [ProviderSettings.Of("engine", alias: "primary")],
            registry,
            catalog: catalog,
            capabilityOverrides: overrides);

        var report = await client.ProbeAsync("tier", [Feature.JsonMode], record: true);
        Assert.Equal(Feature.Streaming | Feature.JsonMode, report.Capabilities!.Features.Value);
        Assert.Equal(Provenance.Probed, report.Capabilities.Features.Provenance);
        Assert.Equal(1, factoryCalls);

        Assert.Equal(Feature.Streaming, client.Capabilities("tier").Features.Value);
        Assert.Equal(Provenance.Override, client.Capabilities("tier").Features.Provenance);
    }

    [Fact]
    public async Task Concurrent_completed_probe_runs_merge_partial_conclusions_without_erasing_each_other()
    {
        var schemaEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var schemaRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ProbeAdapter((request, _) => request.Mechanism switch
        {
            "json_schema" => DelayedEvents(schemaEntered, schemaRelease, new AdapterTextDelta("{\"colour\":\"blue\"}"), new AdapterFinal("stop")),
            "json_mode" => Events(new AdapterTextDelta("[]"), new AdapterFinal("stop")),
            _ => throw new Xunit.Sdk.XunitException("Unexpected concurrent probe request."),
        });
        await using var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);

        var schema = client.ProbeAsync("primary:model", [Feature.JsonSchema]);
        await schemaEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var mode = await client.ProbeAsync("primary:model", [Feature.JsonMode]);
        Assert.Equal(Feature.JsonMode, mode.Capabilities!.Features.Value);
        Assert.Equal(Feature.JsonMode, client.Capabilities("primary:model").Features.Value);

        schemaRelease.TrySetResult();
        var schemaReport = await schema;
        Assert.Equal(Feature.JsonSchema | Feature.JsonMode, schemaReport.Capabilities!.Features.Value);
        Assert.Equal(Feature.JsonSchema | Feature.JsonMode, client.Capabilities("primary:model").Features.Value);
    }

    [Fact]
    public async Task Throwing_feature_cancellation_callback_is_retained_and_feature_token_is_disposed_after_close_cleanup()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var sentinel = new InvalidOperationException("probe cancellation callback");
        CancellationToken featureToken = default;
        var adapter = new ProbeAdapter((_, token) => ThrowingCancellationCallback(token, entered, callbackEntered, sentinel, captured => featureToken = captured));
        var client = AsyncClient.FromAdapters([new ProviderRegistration("primary", adapter)]);
        var pending = client.ProbeAsync("primary:model", [Feature.JsonMode], timeoutS: 30);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(1));

        var closing = client.DisposeAsync().AsTask();
        await callbackEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var close = await Assert.ThrowsAnyAsync<Exception>(() => closing);
        Assert.True(ContainsReference(close, sentinel));
        var probeFailure = await Assert.ThrowsAnyAsync<Exception>(() => pending);
        Assert.True(ContainsReference(probeFailure, sentinel));
        Assert.Throws<ObjectDisposedException>(() => _ = featureToken.WaitHandle);
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Streaming_probe_preserves_untested_legacy_schema_profile_but_probed_none_clears_it_for_later_generation()
    {
        var schema = new SchemaSpec(new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("properties", new JsonObject([
                new JsonProperty("colour", new JsonObject([new JsonProperty("type", new JsonString("string"))])),
            ])),
            new JsonProperty("required", new JsonArray([new JsonString("colour")])),
        ]));

        var streamingAdapter = new ProbeAdapter((request, _) => request.Stream
            ? Events(new AdapterTextDelta("one"), new AdapterTextDelta("two"), new AdapterFinal("stop"))
            : Events(new AdapterTextDelta("{\"colour\":\"blue\"}"), new AdapterFinal("stop")));
        await using (var streamingClient = AsyncClient.FromAdapters([
            new ProviderRegistration("primary", streamingAdapter, new Dictionary<string, StructuredOutputProfile>
            {
                ["model"] = new StructuredOutputProfile(JsonSchema: true),
            }),
        ]))
        {
            var report = await streamingClient.ProbeAsync("primary:model", [Feature.Streaming]);
            Assert.Equal(Feature.JsonSchema | Feature.Streaming, report.Capabilities!.Features.Value);
            await streamingClient.GenerateAsync("return blue", target: "primary:model", schema: schema);
            Assert.Equal("json_schema", streamingAdapter.Requests[^1].Mechanism);
        }

        var clearingAdapter = new ProbeAdapter((request, _) => request.Mechanism == "json_schema"
            ? ThrowEvents(ProviderException.Create("schema rejected", "unsupported_input", retryable: false, phase: "generate", provider: "primary"))
            : Events(new AdapterTextDelta("{\"colour\":\"blue\"}"), new AdapterFinal("stop")));
        await using var clearingClient = AsyncClient.FromAdapters([
            new ProviderRegistration("primary", clearingAdapter, new Dictionary<string, StructuredOutputProfile>
            {
                ["model"] = new StructuredOutputProfile(JsonSchema: true),
            }),
        ]);
        var cleared = await clearingClient.ProbeAsync("primary:model", [Feature.JsonSchema]);
        Assert.Equal(Feature.None, cleared.Capabilities!.Features.Value);
        Assert.Equal(Provenance.Probed, cleared.Capabilities.Features.Provenance);
        await clearingClient.GenerateAsync("return blue", target: "primary:model", schema: schema);
        Assert.Equal("prompt", clearingAdapter.Requests[^1].Mechanism);
    }

    [Fact]
    public async Task Async_and_captured_sync_probe_unsafe_callbacks_refuse_self_dispose_while_external_close_completes_cleanup()
    {
        AsyncClient? asyncClient = null;
        var asyncRegistered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Exception? asyncCallbackFailure = null;
        var asyncAdapter = new ProbeAdapter((_, token) => SelfDisposingProbe(token, asyncRegistered, () => asyncCallbackFailure = Record.Exception(() => asyncClient!.DisposeAsync())));
        asyncClient = AsyncClient.FromAdapters([new ProviderRegistration("primary", asyncAdapter)]);
        var asyncProbe = asyncClient.ProbeAsync("primary:model", [Feature.JsonMode]);
        await asyncRegistered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await asyncClient.DisposeAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => asyncProbe);
        Assert.IsType<InvalidOperationException>(asyncCallbackFailure);
        Assert.Equal(1, asyncAdapter.DisposeCalls);

        Client? syncClient = null;
        var syncRegistered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Exception? syncCallbackFailure = null;
        var syncAdapter = new ProbeAdapter((_, token) => SelfDisposingProbe(token, syncRegistered, () => syncCallbackFailure = Record.Exception(() => syncClient!.Dispose())));
        syncClient = Client.FromAdapters([new ProviderRegistration("primary", syncAdapter)]);
        var syncProbe = Task.Run(() => syncClient.Probe("primary:model", [Feature.JsonMode]));
        await syncRegistered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await Task.Run(syncClient.Dispose);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => syncProbe);
        Assert.IsType<InvalidOperationException>(syncCallbackFailure);
        Assert.Equal(1, syncAdapter.DisposeCalls);
    }

    private static async IAsyncEnumerable<AdapterEvent> Events(params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> ThrowEvents(Exception error)
    {
        await Task.Yield();
        throw error;
#pragma warning disable CS0162
        yield break;
#pragma warning restore CS0162
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockingEvents(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource entered,
        TaskCompletionSource cleaned,
        Action<bool>? cancellationAtEntry = null,
        Action<CancellationToken>? tokenAtEntry = null,
        Action<OperationCanceledException>? captureCancellation = null)
    {
        cancellationAtEntry?.Invoke(token.IsCancellationRequested);
        tokenAtEntry?.Invoke(token);
        entered.TrySetResult();
        try
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        catch (OperationCanceledException exception)
        {
            captureCancellation?.Invoke(exception);
            throw;
        }
        finally
        {
            cleaned.TrySetResult();
        }
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> IgnoringCancellationSuccess(TaskCompletionSource entered, TaskCompletionSource release)
    {
        entered.TrySetResult();
        await release.Task;
        yield return new AdapterTextDelta("[]");
        yield return new AdapterFinal("stop");
    }

    private static async IAsyncEnumerable<AdapterEvent> DelayedEvents(
        TaskCompletionSource entered,
        TaskCompletionSource release,
        params AdapterEvent[] events)
    {
        entered.TrySetResult();
        await release.Task;
        foreach (var item in events)
        {
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> ThrowingCancellationCallback(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource entered,
        TaskCompletionSource callbackEntered,
        Exception sentinel,
        Action<CancellationToken> capture)
    {
        var delay = Task.Delay(Timeout.InfiniteTimeSpan, token);
        using var registration = token.Register(() =>
        {
            callbackEntered.TrySetResult();
            throw sentinel;
        });
        capture(token);
        entered.TrySetResult();
        await delay;
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> SelfDisposingProbe(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource registered,
        Action callback)
    {
        var delay = Task.Delay(Timeout.InfiniteTimeSpan, token);
        using var registration = token.UnsafeRegister(_ => callback(), null);
        registered.TrySetResult();
        await delay;
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> TimeoutThenProviderFailure(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource cleaned)
    {
        try
        {
            try
            {
                await Task.Delay(Timeout.InfiniteTimeSpan, token);
            }
            catch (OperationCanceledException)
            {
                // The adapter observed and suppressed the owned timer before reporting its own rejection.
            }
            throw ProviderException.Create("rejected after cancellation", "unsupported_input", retryable: false, phase: "generate", provider: "primary");
        }
        finally
        {
            cleaned.TrySetResult();
        }
#pragma warning disable CS0162
        yield break;
#pragma warning restore CS0162
    }

    private sealed class ProbeAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> events) : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return events(request, cancellationToken);
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private static bool ContainsReference(Exception actual, Exception expected) =>
        ReferenceEquals(actual, expected) ||
        actual is AggregateException aggregate && aggregate.InnerExceptions.Any(item => ContainsReference(item, expected)) ||
        actual.InnerException is { } inner && ContainsReference(inner, expected);
}
