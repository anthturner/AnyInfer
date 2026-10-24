using System.Numerics;
using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Core;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Pure cache-policy, placement, and prefix-diagnostic controls.</summary>
public sealed class CachePlanningTests
{
    [Fact]
    public void Policy_and_cache_value_snapshots_validate_and_copy_inputs()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => new CachePolicy((CacheMode)99));
        Assert.Throws<ArgumentOutOfRangeException>(() => new CachePolicy(minSegmentTokens: -1));
        Assert.Throws<ArgumentOutOfRangeException>(() => new CachePolicy(maxMarks: 0));
        Assert.False(new CachePolicy(CacheMode.Off).Active);
        Assert.True(new CachePolicy().Active);

        var marks = new List<CacheMark> { new(-2, 9) };
        var reasons = new List<string> { "reason" };
        var plan = new CachePlan(CacheMechanism.Explicit, marks, 9, reasons);
        marks.Clear();
        reasons.Clear();
        Assert.Equal(-2, Assert.Single(plan.Marks).Segment);
        Assert.Equal("reason", Assert.Single(plan.Reasons));

        var values = new List<int> { -2, 3 };
        var wire = new WireRequest("model", [Message.User("cache")], new Sampling(), cacheMarks: values);
        values.Clear();
        Assert.Equal([-2, 3], wire.CacheMarks);
        Assert.Throws<ArgumentOutOfRangeException>(() => Descriptor((CacheMechanism)99));
        Assert.Throws<ArgumentOutOfRangeException>(() => Descriptor(CacheMechanism.Explicit, maxMarks: -1));
        Assert.Throws<ArgumentOutOfRangeException>(() => Descriptor(CacheMechanism.Explicit, minTokens: -1));
    }

    [Fact]
    public void Null_off_undeclared_and_explicit_without_placement_are_estimator_free_with_exact_reasons()
    {
        var request = Request();
        var estimator = new RecordingEstimator();
        var explicitDescriptor = Descriptor(CacheMechanism.Explicit);

        Assert.False(CachePlanning.Plan(request, null, Placement(), explicitDescriptor, estimator).Active);
        Assert.False(CachePlanning.Plan(request, new CachePolicy(CacheMode.Off), Placement(), explicitDescriptor, estimator).Active);
        var undeclared = CachePlanning.Plan(request, new CachePolicy(), Placement(), Descriptor(null), estimator);
        var missingFeature = CachePlanning.Plan(request, new CachePolicy(), Features(Feature.Streaming), explicitDescriptor, estimator);

        Assert.Equal("the target declares no prompt-cache mechanism", Assert.Single(undeclared.Reasons));
        Assert.Equal("the target's capabilities do not include cache placement", Assert.Single(missingFeature.Reasons));
        Assert.Empty(estimator.Inputs);
    }

    [Fact]
    public void Implicit_plan_estimates_joined_system_then_ordered_tools_then_second_last_non_system_prefix()
    {
        var request = Request(
            [new Message("system", [new Text("sys one")]), new Message("user", [new Text("old user")]),
                new Message("system", [new Text("sys two")]), new Message("assistant", [new Text("old answer")]),
                Message.User("tail")],
            [Tool("first", "one"), Tool("second", "two")]);
        var estimator = new RecordingEstimator(new Dictionary<string, long>(StringComparer.Ordinal)
        {
            ["sys one\nsys two"] = 10,
            ["[{\"name\": \"first\", \"description\": \"one\", \"parameters\": {\"type\": \"object\"}}, {\"name\": \"second\", \"description\": \"two\", \"parameters\": {\"type\": \"object\"}}]"] = 20,
            ["old user"] = 30,
            ["old answer"] = 40,
        });

        var plan = CachePlanning.Plan(request, new CachePolicy(minSegmentTokens: 0), Features(Feature.Streaming), Descriptor(CacheMechanism.Implicit), estimator);

        Assert.Equal(CacheMechanism.Implicit, plan.Mechanism);
        Assert.Empty(plan.Marks);
        Assert.Equal(100, plan.EstimatedCacheableTokens);
        Assert.Equal("the target caches stable prefixes without being asked", Assert.Single(plan.Reasons));
        Assert.Equal(["sys one\nsys two", "[{\"name\": \"first\", \"description\": \"one\", \"parameters\": {\"type\": \"object\"}}, {\"name\": \"second\", \"description\": \"two\", \"parameters\": {\"type\": \"object\"}}]", "old user", "old answer"], estimator.Inputs);
    }

    [Fact]
    public void Explicit_plan_uses_tool_system_and_second_last_non_system_sentinels_then_sorts_wire_marks()
    {
        var request = Request(
            [new Message("system", [new Text("system")]), new Message("user", [new Text("old user")]),
                new Message("system", [new Text("later system")]), new Message("assistant", [new Text("old answer")]),
                Message.User("tail")],
            [Tool("tool", "description")]);
        var estimator = new RecordingEstimator(new Dictionary<string, long>(StringComparer.Ordinal)
        {
            ["system\nlater system"] = 20,
            ["[{\"name\": \"tool\", \"description\": \"description\", \"parameters\": {\"type\": \"object\"}}]"] = 30,
            ["old user"] = 10,
            ["old answer"] = 20,
        });

        var plan = CachePlanning.Plan(request, new CachePolicy(minSegmentTokens: 0), Placement(), Descriptor(CacheMechanism.Explicit), estimator);

        Assert.Equal(CacheMechanism.Explicit, plan.Mechanism);
        Assert.Equal([-2, -1, 3], plan.Marks.Select(static mark => mark.Segment));
        Assert.Equal(80, plan.EstimatedCacheableTokens);
        Assert.Empty(plan.Reasons);
    }

    [Fact]
    public void Explicit_selection_honors_stable_boundary_ties_floors_caps_and_include_flags()
    {
        var tieAndFloorRequest = Request(
            [new Message("system", [new Text("s")]), new Message("user", [new Text("stable")]),
                new Message("assistant", [new Text("final")])],
            [Tool("tool", "d")]);
        var equalCandidates = CachePlanning.Plan(tieAndFloorRequest, new CachePolicy(minSegmentTokens: 0), Placement(), Descriptor(CacheMechanism.Explicit), new RecordingEstimator(static _ => 5));
        Assert.Equal([-2, -1, 1], equalCandidates.Marks.Select(static mark => mark.Segment));
        Assert.All(equalCandidates.Marks, static mark => Assert.Equal(5, mark.EstimatedTokens));

        var tied = CachePlanning.Plan(tieAndFloorRequest, new CachePolicy(minSegmentTokens: 0, maxMarks: 1), Placement(), Descriptor(CacheMechanism.Explicit, maxMarks: 1), new RecordingEstimator(static _ => 5));
        Assert.Equal([-2], tied.Marks.Select(static mark => mark.Segment));
        Assert.Equal("the target accepts at most 1 marks", Assert.Single(tied.Reasons));

        var tooSmall = CachePlanning.Plan(tieAndFloorRequest, new CachePolicy(minSegmentTokens: 9), Placement(), Descriptor(CacheMechanism.Explicit), new RecordingEstimator(static _ => 8));
        Assert.False(tooSmall.Active);
        Assert.Equal("segments under 9 tokens are not worth a mark", Assert.Single(tooSmall.Reasons));
        var descriptorFloor = CachePlanning.Plan(tieAndFloorRequest, new CachePolicy(minSegmentTokens: 0), Placement(), Descriptor(CacheMechanism.Explicit, minTokens: 9), new RecordingEstimator(static _ => 8));
        Assert.False(descriptorFloor.Active);
        Assert.Equal("segments under 9 tokens are not worth a mark", Assert.Single(descriptorFloor.Reasons));

        var historyRequest = Request(
            [new Message("system", [new Text("s")]), new Message("user", [new Text("first")]),
                new Message("system", [new Text("s2")]), new Message("assistant", [new Text("second")]),
                Message.User("tail")],
            [Tool("tool", "d")]);
        var prefixOnly = CachePlanning.Plan(historyRequest, new CachePolicy(minSegmentTokens: 0, includeTools: false, includeSystem: false), Placement(), Descriptor(CacheMechanism.Explicit), new RecordingEstimator(static _ => 1));
        Assert.Equal([3], prefixOnly.Marks.Select(static mark => mark.Segment));
    }

    [Fact]
    public void Checked_cache_estimation_overflow_is_not_silently_clamped()
    {
        var request = Request([new Message("system", [new Text("system")]), Message.User("user")], [Tool("tool", "d")]);
        var estimator = new RecordingEstimator(static _ => long.MaxValue);

        Assert.Throws<OverflowException>(() => CachePlanning.Plan(request, new CachePolicy(minSegmentTokens: 0), Features(Feature.None), Descriptor(CacheMechanism.Implicit), estimator));
    }

    [Fact]
    public void Prefix_signature_compares_same_and_changed_prefixes_with_scalar_count_and_sorted_tool_keys_without_fixed_hashes()
    {
        var plan = new CachePlan(CacheMechanism.Implicit);
        var first = Request([new Message("system", [new Text("sys😀")]), Message.User("old"), Message.User("tail")], [Tool("tool", "d", "{\"z\":1,\"a\":2}")]);
        var samePrefixDifferentTail = Request([new Message("system", [new Text("sys😀")]), Message.User("old"), Message.User("other tail")], [Tool("tool", "d", "{\"a\":2,\"z\":1}")]);
        var changedSystem = Request([new Message("system", [new Text("other")]), Message.User("old"), Message.User("tail")], [Tool("tool", "d", "{\"a\":2,\"z\":1}")]);

        var signature = plan.PrefixSignature(first);
        Assert.Equal(3, signature.Split(':').Length);
        Assert.StartsWith("4:", signature, StringComparison.Ordinal);
        Assert.Equal(signature, plan.PrefixSignature(samePrefixDifferentTail));
        Assert.NotEqual(signature, plan.PrefixSignature(changedSystem));
    }

    [Fact]
    public async Task Public_client_uses_client_policy_request_off_override_and_exact_custom_adapter_wire_marks()
    {
        var adapter = new CapturingAdapter();
        var observer = new Collector();
        await using var client = PublicClient(adapter, observer, CacheMechanism.Explicit, Placement(), new CachePolicy(minSegmentTokens: 0));
        var request = Request(
            [new Message("system", [new Text("system")]), Message.User("old"), Message.User("tail")],
            [Tool("tool", "description")]);

        var planned = await client.GenerateAsync(request);
        var disabled = await client.GenerateAsync(new GenerationRequest(request.Messages, request.Route, tools: request.Tools, cache: new CachePolicy(CacheMode.Off)));

        Assert.Equal([-2, -1, 1], adapter.Requests[0].CacheMarks);
        Assert.Empty(adapter.Requests[1].CacheMarks);
        Assert.Equal(CacheMechanism.Explicit, planned.CacheMechanism);
        Assert.Null(disabled.CacheMechanism);
        Assert.Collection(observer.Events.OfType<CachePlanned>(),
            planned => { Assert.Equal("explicit", planned.Mechanism); Assert.Equal(3, planned.MarkCount); });
    }

    [Fact]
    public async Task Public_explicit_capable_client_without_an_active_policy_has_no_terminal_cache_mechanism()
    {
        var adapter = new CapturingAdapter();
        var observer = new Collector();
        await using var client = PublicClient(adapter, observer, CacheMechanism.Explicit, Placement());

        var result = await client.GenerateAsync(Request());

        Assert.Null(result.CacheMechanism);
        Assert.Empty(Assert.Single(adapter.Requests).CacheMarks);
        Assert.Empty(observer.Events.OfType<CachePlanned>());
    }

    [Fact]
    public async Task Public_client_keeps_implicit_cache_for_explicit_request_and_refuses_unavailable_or_generic_marks_without_inventing_wire_fields()
    {
        var implicitAdapter = new CapturingAdapter();
        var implicitObserver = new Collector();
        await using (var implicitClient = PublicClient(implicitAdapter, implicitObserver, CacheMechanism.Implicit, Features(Feature.Streaming)))
        {
            var result = await implicitClient.GenerateAsync(Request(cache: new CachePolicy(CacheMode.Explicit, minSegmentTokens: 0)));
            Assert.Equal(CacheMechanism.Implicit, result.CacheMechanism);
        }
        Assert.Empty(Assert.Single(implicitAdapter.Requests).CacheMarks);
        Assert.Equal("implicit", Assert.Single(implicitObserver.Events.OfType<CachePlanned>()).Mechanism);
        var implicitDrop = Assert.Single(implicitObserver.Events.OfType<ParameterDropped>());
        Assert.Equal("cache.mode", implicitDrop.Parameter);
        Assert.Equal("the target offers implicit caching, not explicit marks", implicitDrop.Reason);

        var refusedAdapter = new CapturingAdapter();
        var refusedObserver = new Collector();
        await using (var refusedClient = PublicClient(refusedAdapter, refusedObserver, CacheMechanism.Explicit, Features(Feature.Streaming)))
        {
            var result = await refusedClient.GenerateAsync(Request(cache: new CachePolicy(CacheMode.Explicit, minSegmentTokens: 0)));
            Assert.Null(result.CacheMechanism);
        }
        Assert.Empty(Assert.Single(refusedAdapter.Requests).CacheMarks);
        Assert.Empty(refusedObserver.Events.OfType<CachePlanned>());
        Assert.Equal("the target's capabilities do not include cache placement", Assert.Single(refusedObserver.Events.OfType<ParameterDropped>()).Reason);

        var genericAdapter = new CapturingAdapter();
        var genericObserver = new Collector();
        await using (var genericClient = PublicClient(genericAdapter, genericObserver, null, Placement()))
        {
            var result = await genericClient.GenerateAsync(Request(cache: new CachePolicy(minSegmentTokens: 0)));
            Assert.Null(result.CacheMechanism);
        }
        Assert.Empty(Assert.Single(genericAdapter.Requests).CacheMarks);
        Assert.Empty(genericObserver.Events.OfType<CachePlanned>());
        var genericDrop = Assert.Single(genericObserver.Events.OfType<ParameterDropped>());
        Assert.Equal("cache.mode", genericDrop.Parameter);
        Assert.Equal("the target declares no prompt-cache mechanism", genericDrop.Reason);
    }

    [Fact]
    public async Task Public_retry_replans_while_schema_repair_reuses_the_original_marks_and_manifest_facts()
    {
        var retryAdapter = new ScriptedCapturingAdapter((call, _, token) => call == 1
            ? Throw(token, new TransportException("retry", retryable: true, phase: "generate"))
            : Events(token));
        var retryObserver = new Collector();
        await using (var retryClient = PublicClient(retryAdapter, retryObserver, CacheMechanism.Explicit, Placement(), new CachePolicy(minSegmentTokens: 0)))
        {
            var result = await retryClient.GenerateAsync(new GenerationRequest(
                [new Message("system", [new Text("system")]), Message.User("old"), Message.User("tail")],
                new Route(["cache:model"], new Retry(2, 0, 0)), cache: null));
            Assert.Equal(CacheMechanism.Explicit, result.CacheMechanism);
        }
        Assert.Equal(2, retryAdapter.Requests.Count);
        Assert.Equal(2, retryObserver.Events.OfType<CachePlanned>().Count());
        Assert.Equal(retryAdapter.Requests[0].CacheMarks, retryAdapter.Requests[1].CacheMarks);

        var repairAdapter = new ScriptedCapturingAdapter((call, _, token) => call == 1
            ? Events(token, new AdapterTextDelta("\"wrong\""), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("\"correct\""), new AdapterFinal("stop")));
        var repairObserver = new Collector();
        await using (var repairClient = PublicClient(repairAdapter, repairObserver, CacheMechanism.Explicit, Placement(), new CachePolicy(minSegmentTokens: 0)))
        {
            var result = await repairClient.GenerateAsync(new GenerationRequest(
                [new Message("system", [new Text("system")]), Message.User("old"), Message.User("tail")],
                new Route(["cache:model"]), schema: new SchemaSpec(Assert.IsType<JsonObject>(JsonReader.Read("{\"const\":\"correct\"}"))), repair: new Repair(1)));
            Assert.Equal("explicit", result.Manifest!.Cache.Mechanism);
            Assert.Equal(2, result.Manifest.Cache.MarkCount);
            Assert.Equal(CacheMechanism.Explicit, result.CacheMechanism);
        }
        Assert.Equal(2, repairAdapter.Requests.Count);
        Assert.Equal(repairAdapter.Requests[0].CacheMarks, repairAdapter.Requests[1].CacheMarks);
        Assert.Single(repairObserver.Events.OfType<CachePlanned>());
    }

    [Fact]
    public async Task Frozen_client_ignores_cache_policy_and_does_not_add_wire_work()
    {
        var adapter = new CapturingAdapter();
        await using var client = new AsyncClient([new ProviderRegistration("cache", adapter)], new SystemOperationClock());

        var result = await client.GenerateAsync(Request(cache: new CachePolicy(minSegmentTokens: 0)));

        Assert.Empty(Assert.Single(adapter.Requests).CacheMarks);
        Assert.Null(result.CacheMechanism);
    }

    [Fact]
    public async Task Public_async_and_sync_streams_project_cache_mechanism_with_or_without_manifest_capture()
    {
        var asyncAdapter = new CapturingAdapter();
        await using (var client = PublicClient(asyncAdapter, new Collector(), CacheMechanism.Explicit, Placement(), new CachePolicy(minSegmentTokens: 0)))
        {
            await using var capturedStream = client.StreamAsync(Request(), manifest: true);
            var captured = await capturedStream.CollectAsync();
            Assert.Equal(CacheMechanism.Explicit, captured.CacheMechanism);
            Assert.Same(captured, capturedStream.Result);
            Assert.NotNull(captured.Manifest);

            await using var uncapturedStream = client.StreamAsync(Request(), manifest: false);
            var uncaptured = await uncapturedStream.CollectAsync();
            Assert.Equal(CacheMechanism.Explicit, uncaptured.CacheMechanism);
            Assert.Same(uncaptured, uncapturedStream.Result);
            Assert.Null(uncaptured.Manifest);
        }

        using var syncClient = PublicSyncClient(new CapturingAdapter(), CacheMechanism.Explicit, Placement(), new CachePolicy(minSegmentTokens: 0));
        using var syncStream = syncClient.Stream(Request(), manifest: true);
        var synchronous = syncStream.Collect();
        Assert.Equal(CacheMechanism.Explicit, synchronous.CacheMechanism);
        Assert.Same(synchronous, syncStream.Result);
        Assert.NotNull(synchronous.Manifest);
    }

    [Fact]
    public async Task Failed_explicit_target_does_not_leak_its_plan_when_implicit_fallback_wins()
    {
        var explicitAdapter = new ScriptedCapturingAdapter((_, _, token) =>
            Throw(token, new TransportException("failed explicit", retryable: false, phase: "generate")));
        var implicitAdapter = new CapturingAdapter();
        var registry = new ProviderRegistry([
            new ProviderDescriptor(
                "explicit", "Explicit", (_, _) => ValueTask.FromResult<IAsyncDisposable>(explicitAdapter),
                staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = Placement() },
                cacheMechanism: CacheMechanism.Explicit),
            new ProviderDescriptor(
                "implicit", "Implicit", (_, _) => ValueTask.FromResult<IAsyncDisposable>(implicitAdapter),
                staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = Features(Feature.Streaming) },
                cacheMechanism: CacheMechanism.Implicit),
        ]);
        await using var client = new AsyncClient(
            [ProviderSettings.Of("explicit"), ProviderSettings.Of("implicit")], registry,
            cachePolicy: new CachePolicy(minSegmentTokens: 0), estimator: new RecordingEstimator(static _ => 10));

        var result = await client.GenerateAsync(new GenerationRequest(
            [new Message("system", [new Text("system")]), Message.User("old"), Message.User("tail")],
            new Route(["explicit:model", "implicit:model"])));

        Assert.Single(explicitAdapter.Requests);
        Assert.Single(implicitAdapter.Requests);
        Assert.NotEmpty(explicitAdapter.Requests[0].CacheMarks);
        Assert.Empty(implicitAdapter.Requests[0].CacheMarks);
        Assert.Equal("implicit", result.Target!.ProviderId);
        Assert.Equal(CacheMechanism.Implicit, result.CacheMechanism);
    }

    [Fact]
    public async Task Implicit_prefix_diagnostic_is_per_client_per_target_and_only_follows_a_changed_prefix()
    {
        var alpha = new CapturingAdapter();
        var beta = new CapturingAdapter();
        var observer = new Collector();
        await using (var client = ImplicitClient(alpha, beta, observer))
        {
            await client.GenerateAsync(CacheRequest("alpha", "alpha first"));
            await client.GenerateAsync(CacheRequest("alpha", "alpha first"));
            await client.GenerateAsync(CacheRequest("beta", "beta first"));
            Assert.Empty(observer.Events.OfType<ProviderDiagnostic>());
            observer.Events.Clear();

            var changed = await client.GenerateAsync(CacheRequest("alpha", "alpha changed", new CachePolicy(CacheMode.Explicit, minSegmentTokens: 0)));
            var facts = observer.Events.Where(static item => item is ProviderDiagnostic or ParameterDropped or CachePlanned).ToArray();
            Assert.Collection(facts,
                item => Assert.IsType<ProviderDiagnostic>(item),
                item => { var drop = Assert.IsType<ParameterDropped>(item); Assert.Equal("cache.mode", drop.Parameter); Assert.Equal("the target offers implicit caching, not explicit marks", drop.Reason); },
                item => Assert.Equal("implicit", Assert.IsType<CachePlanned>(item).Mechanism));
            var diagnostic = Assert.IsType<ProviderDiagnostic>(facts[0]);
            Assert.Equal("alpha", diagnostic.Target!.ProviderId);
            Assert.Equal("cache.prefix-unstable", diagnostic.Diagnostic.Code);
            Assert.Equal("info", diagnostic.Diagnostic.Severity);
            Assert.Equal("the cacheable prefix changed since the last request to this target, so the provider's prompt cache will not be hit", diagnostic.Diagnostic.Message);
            Assert.Contains(diagnostic.Diagnostic.Message, changed.Manifest!.Notes);
        }

        var isolatedObserver = new Collector();
        await using (var isolatedClient = ImplicitClient(new CapturingAdapter(), new CapturingAdapter(), isolatedObserver))
        {
            await isolatedClient.GenerateAsync(CacheRequest("alpha", "isolated first"));
        }
        Assert.Empty(isolatedObserver.Events.OfType<ProviderDiagnostic>());

        var explicitObserver = new Collector();
        await using (var explicitClient = PublicClient(new CapturingAdapter(), explicitObserver, CacheMechanism.Explicit, Placement(), new CachePolicy(minSegmentTokens: 0)))
        {
            await explicitClient.GenerateAsync(Request([new Message("system", [new Text("explicit first")]), Message.User("old"), Message.User("tail")]));
            await explicitClient.GenerateAsync(Request([new Message("system", [new Text("explicit changed")]), Message.User("old"), Message.User("tail")]));
        }
        Assert.Empty(explicitObserver.Events.OfType<ProviderDiagnostic>());
    }

    [Fact]
    public async Task Implicit_cache_estimates_above_int32_survive_event_dictionary_and_manifest_json_roundtrips()
    {
        const long expected = (long)int.MaxValue + 17;
        var adapter = new CapturingAdapter();
        var observer = new Collector();
        await using var client = PublicClient(adapter, observer, CacheMechanism.Implicit, Features(Feature.Streaming), new CachePolicy(minSegmentTokens: 0), new RecordingEstimator(static _ => expected));

        var result = await client.GenerateAsync(new GenerationRequest([new Message("system", [new Text("system")]), Message.User("tail")], new Route(["cache:model"])));

        var planned = Assert.Single(observer.Events.OfType<CachePlanned>());
        Assert.Equal(expected, planned.EstimatedCacheableTokens);
        var eventValue = Assert.IsType<JsonInteger>(planned.ToDictionary().Properties.Single(static property => property.Name == "estimated_cacheable_tokens").Value);
        Assert.Equal(new BigInteger(expected), eventValue.Value);
        Assert.Equal(expected, result.Manifest!.Cache.EstimatedCacheableTokens);
        var roundTripped = RunManifest.FromJson(result.Manifest.ToJson());
        Assert.Equal(expected, roundTripped.Cache.EstimatedCacheableTokens);
    }

    private static GenerationRequest Request(IEnumerable<Message>? messages = null, IEnumerable<ToolSpec>? tools = null, CachePolicy? cache = null) =>
        new(messages ?? [new Message("system", [new Text("system")]), Message.User("old"), Message.User("tail")], new Route(["cache:model"]), tools: tools, cache: cache);

    private static ToolSpec Tool(string name, string description, string parameters = "{\"type\":\"object\"}") =>
        new(name, description, Assert.IsType<JsonObject>(JsonReader.Read(parameters)));

    private static ModelCapabilities Placement() => Features(Feature.CachePlacement | Feature.Streaming);

    private static ModelCapabilities Features(Feature features) => new(features: new Sourced<Feature>(features, Provenance.Catalog));

    private static ProviderDescriptor Descriptor(CacheMechanism? mechanism, int maxMarks = 0, long minTokens = 0) => new(
        "cache", "Cache", static (_, _) => ValueTask.FromException<IAsyncDisposable>(new InvalidOperationException("factory is not used by pure planning")),
        cacheMechanism: mechanism, cacheMaxMarks: maxMarks, cacheMinTokens: minTokens);

    private static AsyncClient PublicClient(IProviderAdapter adapter, Collector observer, CacheMechanism? mechanism, ModelCapabilities capabilities, CachePolicy? cachePolicy = null, ITokenEstimator? estimator = null) =>
        new([ProviderSettings.Of("cache")], new ProviderRegistry([new ProviderDescriptor(
            "cache", "Cache", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = capabilities },
            cacheMechanism: mechanism)]), observers: [observer], estimator: estimator ?? new RecordingEstimator(static _ => 10), cachePolicy: cachePolicy);

    private static Client PublicSyncClient(IProviderAdapter adapter, CacheMechanism? mechanism, ModelCapabilities capabilities, CachePolicy? cachePolicy = null) =>
        new([ProviderSettings.Of("cache")], new ProviderRegistry([new ProviderDescriptor(
            "cache", "Cache", (_, _) => ValueTask.FromResult<IAsyncDisposable>(adapter),
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = capabilities },
            cacheMechanism: mechanism)]), estimator: new RecordingEstimator(static _ => 10), cachePolicy: cachePolicy);

    private static AsyncClient ImplicitClient(IProviderAdapter alpha, IProviderAdapter beta, Collector observer) =>
        new([ProviderSettings.Of("alpha"), ProviderSettings.Of("beta")], new ProviderRegistry([
            new ProviderDescriptor("alpha", "Alpha", (_, _) => ValueTask.FromResult<IAsyncDisposable>(alpha), staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = Features(Feature.Streaming) }, cacheMechanism: CacheMechanism.Implicit),
            new ProviderDescriptor("beta", "Beta", (_, _) => ValueTask.FromResult<IAsyncDisposable>(beta), staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal) { ["model"] = Features(Feature.Streaming) }, cacheMechanism: CacheMechanism.Implicit),
        ]), observers: [observer], cachePolicy: new CachePolicy(minSegmentTokens: 0));

    private static GenerationRequest CacheRequest(string provider, string system, CachePolicy? cache = null) =>
        new([new Message("system", [new Text(system)]), Message.User("old"), Message.User("tail")], new Route([$"{provider}:model"]), cache: cache);

    private sealed class RecordingEstimator : ITokenEstimator
    {
        private readonly Func<string, long> _estimate;
        public RecordingEstimator(Func<string, long>? estimate = null) => _estimate = estimate ?? (static value => value.Length);
        public RecordingEstimator(IReadOnlyDictionary<string, long> estimates)
        {
            ArgumentNullException.ThrowIfNull(estimates);
            _estimate = value => estimates[value];
        }
        internal List<string> Inputs { get; } = [];
        public TokenEstimate Estimate(string value)
        {
            Inputs.Add(value);
            return new TokenEstimate(_estimate(value), 0);
        }
    }

    private sealed class CapturingAdapter : IProviderAdapter
    {
        internal List<WireRequest> Requests { get; } = [];
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return Events(cancellationToken);
        }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class ScriptedCapturingAdapter(Func<int, WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) : IProviderAdapter
    {
        private int _calls;
        internal List<WireRequest> Requests { get; } = [];
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return script(++_calls, request, cancellationToken);
        }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class Collector : IObserver
    {
        internal List<TelemetryEvent> Events { get; } = [];
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Add(telemetryEvent);
    }

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta("ok");
        await Task.Yield();
        yield return new AdapterFinal("stop");
    }

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token, params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw([EnumeratorCancellation] CancellationToken token, Exception exception)
    {
        await Task.CompletedTask;
        token.ThrowIfCancellationRequested();
        System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(exception).Throw();
        yield break;
    }
}
