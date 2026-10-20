using System.Runtime.CompilerServices;
using AnyInfer.Capabilities;
using AnyInfer.Config;
using AnyInfer.Credentials;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Inert configuration controls for retrieval operation routes.</summary>
public sealed class OperationRouteConfigTests
{
    [Fact]
    public void Constructor_copies_supported_operation_keys_preserves_route_identity_and_repeated_positions()
    {
        var embedding = new Route(["embed:model", "embed:model"]);
        var rerank = new Route(["rerank:model"]);
        var supplied = new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Embedding] = embedding,
            [InferenceOperation.Rerank] = rerank,
        };

        var config = new AnyInferConfig(operationRoutes: supplied);
        supplied.Clear();

        Assert.Same(embedding, config.OperationRoutes[InferenceOperation.Embedding]);
        Assert.Same(rerank, config.OperationRoutes[InferenceOperation.Rerank]);
        Assert.Equal(["embed:model", "embed:model"], config.OperationRoutes[InferenceOperation.Embedding].Targets);
        Assert.Equal(["rerank:model"], config.OperationRoutes[InferenceOperation.Rerank].Targets);
        if (config.OperationRoutes is IDictionary<InferenceOperation, Route> mutable)
        {
            Assert.Throws<NotSupportedException>(() => mutable.Add(InferenceOperation.Embedding, embedding));
        }
    }

    [Fact]
    public void Constructor_rejects_generation_unknown_and_null_operation_routes()
    {
        Assert.Throws<ConfigException>(() => new AnyInferConfig(operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Generation] = new Route(["generation:model"]),
        }));
        Assert.Throws<ConfigException>(() => new AnyInferConfig(operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [(InferenceOperation)999] = new Route(["unknown:model"]),
        }));
        Assert.Throws<ConfigException>(() => new AnyInferConfig(operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Embedding] = null!,
        }));
    }

    [Fact]
    public void Loads_treats_absent_null_and_empty_operation_routes_as_empty_and_omits_them_when_dumping()
    {
        foreach (var text in new[] { "{}", "{\"operation_routes\":null}", "{\"operation_routes\":{}}" })
        {
            var config = AnyInferConfig.Loads(text);
            Assert.Empty(config.OperationRoutes);
            Assert.DoesNotContain("operation_routes", config.Dumps(), StringComparison.Ordinal);
        }
    }

    [Fact]
    public void Loads_and_dumps_only_embedding_and_rerank_routes_with_exact_target_order()
    {
        var config = AnyInferConfig.Loads("""
            {"operation_routes":{
              "embedding":["embed:model","embed:model"],
              "rerank":["rerank:model"]
            }}
            """);

        Assert.Equal(["embed:model", "embed:model"], config.OperationRoutes[InferenceOperation.Embedding].Targets);
        Assert.Equal(["rerank:model"], config.OperationRoutes[InferenceOperation.Rerank].Targets);

        var rendered = config.Dumps();
        Assert.Contains("\"operation_routes\"", rendered, StringComparison.Ordinal);
        Assert.Contains("\"embedding\"", rendered, StringComparison.Ordinal);
        Assert.Contains("\"rerank\"", rendered, StringComparison.Ordinal);
        var reparsed = AnyInferConfig.Loads(rendered);
        Assert.Equal(config.OperationRoutes[InferenceOperation.Embedding].Targets, reparsed.OperationRoutes[InferenceOperation.Embedding].Targets);
        Assert.Equal(config.OperationRoutes[InferenceOperation.Rerank].Targets, reparsed.OperationRoutes[InferenceOperation.Rerank].Targets);
    }

    [Theory]
    [InlineData("{\"operation_routes\":[]}")]
    [InlineData("{\"operation_routes\":{\"generation\":[\"fixture:model\"]}}")]
    [InlineData("{\"operation_routes\":{\"unknown\":[\"fixture:model\"]}}")]
    [InlineData("{\"operation_routes\":{\"embedding\":null}}")]
    [InlineData("{\"operation_routes\":{\"embedding\":[]}}")]
    [InlineData("{\"operation_routes\":{\"embedding\":[\"\"]}}")]
    [InlineData("{\"operation_routes\":{\"embedding\":[\"   \"]}}")]
    [InlineData("{\"operation_routes\":{\"embedding\":[1]}}")]
    public void Loads_rejects_invalid_operation_route_shapes_keys_and_targets(string text)
    {
        Assert.Throws<ConfigException>(() => AnyInferConfig.Loads(text));
    }

    [Fact]
    public void Dump_refuses_retry_health_and_context_route_details_that_format_one_cannot_represent()
    {
        Assert.Throws<ConfigException>(() => new AnyInferConfig(operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Embedding] = new Route(["embed:model"], retry: new Retry(3)),
        }).Dumps());
        Assert.Throws<ConfigException>(() => new AnyInferConfig(operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Embedding] = new Route(["embed:model"], healthGate: false),
        }).Dumps());
        Assert.Throws<ConfigException>(() => new AnyInferConfig(operationRoutes: new Dictionary<InferenceOperation, Route>
        {
            [InferenceOperation.Rerank] = new Route(["rerank:model"], contextWindowTargets: ["overflow:model"]),
        }).Dumps());
    }

    [Fact]
    public void Loading_constructing_and_dumping_operation_routes_stays_inert_to_credential_resolution_and_factories()
    {
        var resolver = new CountingResolver();
        var factoryCalls = 0;
        var registry = new ProviderRegistry([
            new ProviderDescriptor("fixture", "Fixture", (_, _) =>
            {
                factoryCalls++;
                return ValueTask.FromResult<IAsyncDisposable>(new EmptyAdapter());
            }),
        ]);
        var chain = new ResolverChain([resolver]);

        var loaded = AnyInferConfig.Loads("""
            {"providers":[{"id":"fixture","api_key":"count://inert"}],
             "operation_routes":{"embedding":["fixture:model"]}}
            """, registry, chain);
        var constructed = new AnyInferConfig(
            [ProviderSettings.Of("fixture", apiKey: "count://inert")],
            operationRoutes: new Dictionary<InferenceOperation, Route>
            {
                [InferenceOperation.Rerank] = new Route(["fixture:model"]),
            });

        _ = loaded.Dumps();
        _ = constructed.Dumps();

        Assert.Equal(0, resolver.ResolveCalls);
        Assert.Equal(0, factoryCalls);
    }

    private sealed class CountingResolver : ICredentialResolver
    {
        internal int ResolveCalls { get; private set; }

        public bool Handles(string reference) => reference.StartsWith("count://", StringComparison.Ordinal);

        public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            ResolveCalls++;
            return ValueTask.FromResult("resolved");
        }
    }

    private sealed class EmptyAdapter : IProviderAdapter
    {
        public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
            WireRequest request,
            [EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await Task.Yield();
            yield break;
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
