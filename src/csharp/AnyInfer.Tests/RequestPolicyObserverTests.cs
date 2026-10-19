using System.Runtime.CompilerServices;
using AnyInfer;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Json;
using AnyInfer.Providers;
using JsonDocument = System.Text.Json.JsonDocument;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Observer-only controls for the bounded early-stream raw-read cancellation predicate.</summary>
public sealed class RequestPolicyObserverTests
{
    private static readonly TimeSpan JoinTimeout = TimeSpan.FromSeconds(1);

    [Fact]
    public async Task Accepts_the_declared_caller_token_after_the_fixture_observes_the_read_cancellation()
    {
        using var caller = new CancellationTokenSource();
        using var observed = new CancellationTokenSource();
        caller.Cancel();
        observed.Cancel();

        await RawReadCancellation.ObserveAsync(Oracle(new OperationCanceledException(caller.Token), caller.Token, observed.Token, cancellationObserved: true), JoinTimeout);
    }

    [Fact]
    public async Task Accepts_the_actual_observed_read_token_after_the_fixture_observes_it()
    {
        using var caller = new CancellationTokenSource();
        using var observed = new CancellationTokenSource();
        caller.Cancel();
        observed.Cancel();

        await RawReadCancellation.ObserveAsync(Oracle(new OperationCanceledException(observed.Token), caller.Token, observed.Token, cancellationObserved: true), JoinTimeout);
    }

    [Fact]
    public async Task Refuses_a_successful_pending_read()
    {
        using var caller = new CancellationTokenSource();
        using var observed = new CancellationTokenSource();
        caller.Cancel();
        observed.Cancel();

        await Assert.ThrowsAsync<InvalidOperationException>(() => RawReadCancellation.ObserveAsync(
            new RawReadCancellationOracle(Task.CompletedTask, caller.Token, observed.Token, CancellationObserved: true), JoinTimeout));
    }

    [Fact]
    public async Task Rethrows_an_unrelated_cancellation_by_exact_identity()
    {
        using var caller = new CancellationTokenSource();
        using var observed = new CancellationTokenSource();
        using var unrelated = new CancellationTokenSource();
        caller.Cancel();
        observed.Cancel();
        unrelated.Cancel();
        var source = new OperationCanceledException(unrelated.Token);

        var thrown = await Assert.ThrowsAsync<OperationCanceledException>(() => RawReadCancellation.ObserveAsync(
            Oracle(source, caller.Token, observed.Token, cancellationObserved: true), JoinTimeout));

        Assert.Same(source, thrown);
    }

    [Fact]
    public async Task Refuses_a_caller_requested_cancellation_without_an_observed_fixture_barrier()
    {
        using var caller = new CancellationTokenSource();
        caller.Cancel();
        var source = new OperationCanceledException(caller.Token);

        var thrown = await Assert.ThrowsAsync<OperationCanceledException>(() => RawReadCancellation.ObserveAsync(
            Oracle(source, caller.Token, observedToken: null, cancellationObserved: false), JoinTimeout));

        Assert.Same(source, thrown);
    }

    [Fact]
    public async Task Refuses_an_observed_read_token_that_was_not_requested()
    {
        using var caller = new CancellationTokenSource();
        using var observed = new CancellationTokenSource();
        caller.Cancel();
        var source = new OperationCanceledException(observed.Token);

        var thrown = await Assert.ThrowsAsync<OperationCanceledException>(() => RawReadCancellation.ObserveAsync(
            Oracle(source, caller.Token, observed.Token, cancellationObserved: true), JoinTimeout));

        Assert.Same(source, thrown);
    }

    [Fact]
    public async Task Refuses_an_observed_read_cancellation_when_the_declared_caller_was_not_requested()
    {
        using var caller = new CancellationTokenSource();
        using var observed = new CancellationTokenSource();
        observed.Cancel();
        var source = new OperationCanceledException(observed.Token);

        var thrown = await Assert.ThrowsAsync<OperationCanceledException>(() => RawReadCancellation.ObserveAsync(
            Oracle(source, caller.Token, observed.Token, cancellationObserved: true), JoinTimeout));

        Assert.Same(source, thrown);
    }

    [Fact]
    public async Task Public_clients_distinguish_default_from_catalog_context_floors_and_record_the_default_heuristic()
    {
        const string prompt = "abcdefgh";
        var literalFloor = new FixedEstimator(new TokenEstimate(10, 10));
        var defaultInputs = new List<string>();
        var defaultAdapter = new CompletedAdapter();
        await using (var client = CreateClient(
            defaultAdapter,
            defaultCapabilities: new ModelCapabilities(contextWindow: new Sourced<int>(4, Provenance.Default)),
            staticCapabilities: null,
            literalFloor))
        {
            Assert.Equal("ok", (await client.GenerateAsync(prompt, target: "fixture:model")).Text);
        }

        Assert.Equal(1, defaultAdapter.Calls);

        var catalogAdapter = new CompletedAdapter();
        await using (var client = CreateClient(
            catalogAdapter,
            defaultCapabilities: null,
            staticCapabilities: new Dictionary<string, ModelCapabilities>(StringComparer.Ordinal)
            {
                ["model"] = new ModelCapabilities(contextWindow: new Sourced<int>(4, Provenance.Catalog)),
            },
            literalFloor))
        {
            var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(() => client.GenerateAsync(prompt, target: "fixture:model"));
            Assert.IsType<ContextLengthException>(Assert.Single(failure.Attempts).Error);
        }

        Assert.Equal(0, catalogAdapter.Calls);

        var heuristicAdapter = new CompletedAdapter();
        await using (var client = CreateClient(
            heuristicAdapter,
            defaultCapabilities: new ModelCapabilities(contextWindow: new Sourced<int>(4, Provenance.Default)),
            staticCapabilities: null,
            new PolicyCase.RecordingEstimator(new HeuristicTokenEstimator(), defaultInputs)))
        {
            Assert.Equal("ok", (await client.GenerateAsync(prompt, target: "fixture:model")).Text);
        }

        Assert.Single(defaultInputs);
        Assert.Equal(prompt, defaultInputs[0]);
        Assert.Equal(1, heuristicAdapter.Calls);
    }

    [Fact]
    public async Task Public_stream_preserves_fragmented_tool_deltas_before_the_terminal_result()
    {
        var adapter = new FragmentedToolAdapter();
        await using var client = CreateClient(adapter, null, null, new HeuristicTokenEstimator());
        var events = new List<StreamEvent>();

        await foreach (var item in client.StreamAsync("tool", target: "fixture:model"))
        {
            events.Add(item);
        }

        var deltas = events.OfType<ToolCallDelta>().ToArray();
        Assert.Collection(deltas,
            first =>
            {
                Assert.Equal(0, first.Index);
                Assert.Equal("call_1", first.CallId);
                Assert.Equal("lookup", first.Name);
                Assert.Equal("{\"value\":", first.ArgumentsFragment);
            },
            second =>
            {
                Assert.Equal(0, second.Index);
                Assert.Null(second.CallId);
                Assert.Null(second.Name);
                Assert.Equal("1}", second.ArgumentsFragment);
            });
        var terminalIndex = events.FindIndex(static item => item is StreamEnded);
        Assert.True(terminalIndex > events.FindIndex(static item => item is ToolCallDelta));
        var terminal = Assert.IsType<StreamEnded>(events[terminalIndex]);
        var call = Assert.Single(terminal.Result.ToolCalls);
        Assert.Equal("call_1", call.Id);
        Assert.Equal("lookup", call.Name);
        Assert.True(JsonEquality.TypeAwareEquals(
            new JsonObject([new JsonProperty("value", new JsonInteger(1))]),
            call.Arguments));
    }

    [Fact]
    public async Task Recording_fixture_preserves_an_empty_tool_argument_fragment_in_the_public_stream()
    {
        using var document = JsonDocument.Parse("""
            [{
              "id":"empty-fragment", "instance":"fixture", "transport":"recording",
              "events":[
                {"type":"tool_call_delta", "index":0, "call_id":"call_empty", "name":"lookup", "arguments_fragment":""},
                {"type":"tool_call_delta", "index":0, "call_id":null, "name":null, "arguments_fragment":"{}"},
                {"type":"final", "finish_reason":"tool_calls", "usage":{"input_tokens":1,"output_tokens":1}}
              ]
            }]
            """);
        var resources = new List<System.Text.Json.Nodes.JsonObject>();
        var wires = new List<System.Text.Json.Nodes.JsonObject>();
        using var scripts = ScriptQueue.Create(document.RootElement, resources, new List<System.Text.Json.Nodes.JsonObject>(), static (_, _) => { });
        var adapter = new RecordingAdapter(scripts, wires, "fixture", "recording");
        var descriptor = new ProviderDescriptor("recording", "Recording", (_, _) => new ValueTask<IProviderAdapter>(adapter));
        await using var client = new AsyncClient([ProviderSettings.Of("recording", alias: "fixture")], new ProviderRegistry([descriptor]));
        var events = new List<StreamEvent>();

        await foreach (var item in client.StreamAsync("tool", target: "fixture:model"))
        {
            events.Add(item);
        }

        Assert.Collection(events.OfType<ToolCallDelta>(),
            first => Assert.Equal(string.Empty, first.ArgumentsFragment),
            second => Assert.Equal("{}", second.ArgumentsFragment));
        var terminal = Assert.Single(events.OfType<StreamEnded>());
        Assert.Equal("tool_calls", terminal.Result.FinishReason);
        var call = Assert.Single(terminal.Result.ToolCalls);
        Assert.Equal("call_empty", call.Id);
        Assert.Equal("lookup", call.Name);
        Assert.True(JsonEquality.TypeAwareEquals(new JsonObject([]), call.Arguments));
        scripts.RequireConsumed();
    }

    [Fact]
    public async Task Policy_case_keeps_default_manifest_payloads_null_and_captures_only_the_explicit_redacted_tool_arguments()
    {
        const string secret = "SYNTHETIC-POLICY-SECRET";
        using var document = JsonDocument.Parse("""
            {
              "id":"payload-default-explicit-control", "kind":"tool_stream",
              "instances":[{"id":"alpha","adapter":"openai-compat","api_key":"fixture-token","model":"model"}],
              "client":{"registered_secrets":["SYNTHETIC-POLICY-SECRET"]},
              "request":{"target":"alpha:model","messages":[{"role":"user","content":"tool"}],"tools":[{"name":"lookup","description":"lookup","parameters":{"type":"object"}}],"tool_choice":"required"},
              "procedure":{"name":"tool_stream","capture_modes":["default","explicit"],"consume":"exact"},
              "scripts":[
                {"id":"default","transport":"http","instance":"alpha","status":200,"headers":[{"name":"content-type","value":"application/json"}],"body":{"kind":"json","value":{"choices":[{"message":{"content":null,"tool_calls":[{"id":"default-call","type":"function","function":{"name":"lookup","arguments":"{\"secret\":\"SYNTHETIC-POLICY-SECRET\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,"completion_tokens":0}}}},
                {"id":"explicit","transport":"http","instance":"alpha","status":200,"headers":[{"name":"content-type","value":"application/json"}],"body":{"kind":"json","value":{"choices":[{"message":{"content":null,"tool_calls":[{"id":"explicit-call","type":"function","function":{"name":"lookup","arguments":"{\"secret\":\"SYNTHETIC-POLICY-SECRET\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,"completion_tokens":0}}}}
              ]
            }
            """);

        var observation = await PolicyCase.RunAsync(document.RootElement);
        var operations = observation["value"]!["operations"]!.AsArray();
        var http = observation["value"]!["http"]!.AsArray();
        var defaultManifest = operations[0]!["result"]!["manifest"]!.AsObject();
        var explicitPayload = operations[1]!["result"]!["manifest"]!["payload"]!.AsObject();

        Assert.All(http, item => Assert.Equal("/v1/chat/completions", item!["path"]!.GetValue<string>()));
        Assert.Null(defaultManifest["payload"]);
        var argument = Assert.IsAssignableFrom<System.Text.Json.Nodes.JsonValue>(
            Assert.Single(explicitPayload["tool_arguments"]!.AsArray())).GetValue<string>();
        Assert.DoesNotContain(secret, argument, StringComparison.Ordinal);
        Assert.Contains("[redacted]", argument, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Policy_case_redacts_resolved_authorization_but_retains_noncredential_http_headers()
    {
        const string apiKey = "fixture-api-key-secret";
        using var document = JsonDocument.Parse("""
            {
              "id":"redacted-http-headers-control", "kind":"tool_stream",
              "instances":[{"id":"alpha","adapter":"openai-compat","api_key":"fixture-api-key-secret","model":"model"}],
              "request":{"target":"alpha:model","messages":[{"role":"user","content":"headers"}]},
              "procedure":{"name":"tool_stream","consume":"exact"},
              "scripts":[
                {"id":"stream","transport":"http","instance":"alpha","status":200,"headers":[{"name":"content-type","value":"application/json"}],"body":{"kind":"json","value":{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}}}
              ]
            }
            """);

        var observation = await PolicyCase.RunAsync(document.RootElement);
        var serialized = observation.ToJsonString();
        var headers = observation["value"]!["http"]!.AsArray()[0]!["headers"]!.AsObject();

        Assert.DoesNotContain(apiKey, serialized, StringComparison.Ordinal);
        Assert.Equal("Bearer [redacted]", headers["authorization"]!.GetValue<string>());
        Assert.Equal("application/json", headers["content-type"]!.GetValue<string>());
        Assert.Equal("text/event-stream", headers["accept"]!.GetValue<string>());
    }

    [Fact]
    public async Task Config_consumer_starts_the_second_public_operation_before_releasing_a_held_first_body()
    {
        using var document = JsonDocument.Parse("""
            {
              "id":"config-gated-control", "kind":"config_policy",
              "config":{"format_version":1,"providers":[{"id":"alpha","adapter":"openai-compat","api_key":"fixture-token","base_url":"https://fixture.invalid/v1","limits":{"max_concurrent":1}}]},
              "action":{"target":"alpha:model","messages":[{"role":"user","content":"config limits"}]},
              "procedure":{"name":"config_consumer","consume":"exact"},
              "scripts":[
                {"id":"first","transport":"http","instance":"alpha","status":200,"headers":[{"name":"content-type","value":"application/json"}],"body":{"kind":"raw_utf8","content_type":"application/json","chunks":["{\"choices\":[{\"message\":{\"content\":\"first\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":0}}"]},"gate":{"name":"config-body","owner":"observer","readiness":"body_read_started","release":"finally","cancellation":"propagate"}},
                {"id":"second","transport":"http","instance":"alpha","status":200,"headers":[{"name":"content-type","value":"application/json"}],"body":{"kind":"json","value":{"choices":[{"message":{"content":"second"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":0}}}}
              ]
            }
            """);

        var observation = await PolicyCase.RunAsync(document.RootElement);
        var value = observation["value"]!.AsObject();
        var operations = value["operations"]!.AsArray();
        var sends = value["http"]!.AsArray();

        Assert.Collection(operations,
            first => Assert.Equal(0, first!["index"]!.GetValue<int>()),
            second => Assert.Equal(1, second!["index"]!.GetValue<int>()));
        Assert.Equal(2, sends.Count);
        Assert.Equal("first", sends[0]!["script_id"]!.GetValue<string>());
        Assert.Equal("second", sends[1]!["script_id"]!.GetValue<string>());
    }

    private static RawReadCancellationOracle Oracle(
        OperationCanceledException exception,
        CancellationToken callerToken,
        CancellationToken? observedToken,
        bool cancellationObserved) =>
        new(Task.FromException(exception), callerToken, observedToken, cancellationObserved);

    private static AsyncClient CreateClient(
        IProviderAdapter adapter,
        ModelCapabilities? defaultCapabilities,
        IReadOnlyDictionary<string, ModelCapabilities>? staticCapabilities,
        ITokenEstimator estimator)
    {
        var descriptor = new ProviderDescriptor(
            "fixture",
            "Fixture",
            (_, _) => new ValueTask<IProviderAdapter>(adapter),
            defaultCapabilities: defaultCapabilities,
            staticCapabilities: staticCapabilities);
        return new AsyncClient([ProviderSettings.Of("fixture")], new ProviderRegistry([descriptor]), estimator: estimator);
    }

    private sealed class CompletedAdapter : IProviderAdapter
    {
        public int Calls { get; private set; }

        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            Calls++;
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterTextDelta("ok");
            yield return new AdapterFinal("stop", new Usage(InputTokens: 1, OutputTokens: 1));
            await Task.Yield();
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FragmentedToolAdapter : IProviderAdapter
    {
        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            yield return new AdapterToolCallDelta(0, "call_1", "lookup", "{\"value\":");
            yield return new AdapterToolCallDelta(0, null, null, "1}");
            yield return new AdapterFinal("tool_calls", new Usage(InputTokens: 1, OutputTokens: 1));
            await Task.Yield();
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FixedEstimator(TokenEstimate estimate) : ITokenEstimator
    {
        public TokenEstimate Estimate(string text) => estimate;
    }
}
