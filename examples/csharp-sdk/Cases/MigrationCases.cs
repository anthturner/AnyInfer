using AnyInfer.Capabilities;
using AnyInfer.Config;

namespace AnyInfer.Examples.Cases;

/// <summary>Asserts the version 1 configuration scope the Python-to-C# migration map states.</summary>
internal static class MigrationCases
{
    [ExampleCase("migration.config-v1-accepted-blocks")]
    internal static Task AcceptedBlocks()
    {
        const string json = """
            {
              "format_version": 1,
              "providers": [
                {
                  "id": "openai-compat",
                  "base_url": "https://offline.example/v1",
                  "timeout_s": 30,
                  "limits": {"max_concurrent": 2, "requests_per_minute": 60}
                }
              ],
              "default_route": ["openai-compat:small", "openai-compat:large"],
              "operation_routes": {"embedding": ["tei:embed"], "rerank": ["tei:rerank"]},
              "repair": {"max_attempts": 2},
              "cache": {"mode": "off"},
              "theme": "dark"
            }
            """;
        var config = AnyInferConfig.Loads(json);
        var provider = config.Providers.Single();
        ExampleSupport.Require(provider.ProviderId == "openai-compat"
            && provider.TimeoutS == 30
            && provider.Limits is not null
            && config.Route is { HealthGate: true, HealthTtlS: 30 } route
            && route.Targets.SequenceEqual(["openai-compat:small", "openai-compat:large"])
            && route.Retry == new Retry()
            && route.ContextWindowTargets.Count == 0
            && config.OperationRoutes[InferenceOperation.Embedding].Targets.SequenceEqual(["tei:embed"])
            && config.OperationRoutes[InferenceOperation.Rerank].Targets.SequenceEqual(["tei:rerank"])
            && config.Repair == new Repair(2)
            && config.Cache?.Mode == CacheMode.Off,
            "Version 1 configuration did not load its implemented blocks.");
        return Task.CompletedTask;
    }

    [ExampleCase("migration.config-v1-refused-blocks")]
    internal static Task RefusedBlocks()
    {
        foreach (var key in new[] { "context", "history", "observers", "arena", "arenas", "mcp" })
        {
            var failure = Refuse("{\"format_version\":1,\"" + key + "\":{}}");
            ExampleSupport.Require(failure.Message.Contains($"'{key}' is not implemented", StringComparison.Ordinal),
                $"The {key} block was refused with '{failure.Message}'.");
        }

        Refuse("""{"format_version":1,"sessions":{}}""");
        Refuse("""{"format_version":1,"operation_routes":{"generation":["openai-compat:demo"]}}""");
        Refuse("""{"format_version":2}""");
        return Task.CompletedTask;
    }

    [ExampleCase("migration.config-v1-route-serialization")]
    internal static Task RouteSerialization()
    {
        var plain = new AnyInferConfig(route: new Route(["openai-compat:demo"]));
        ExampleSupport.Require(plain.Dumps().Contains("\"default_route\"", StringComparison.Ordinal),
            "A default-policy route did not serialize as default_route.");
        foreach (var route in new[]
        {
            new Route(["openai-compat:demo"], retry: new Retry(3)),
            new Route(["openai-compat:demo"], healthGate: false),
            new Route(["openai-compat:demo"], contextWindowTargets: ["openai-compat:large"]),
        })
        {
            GuideScripts.ExpectThrows<ConfigException>(
                () => new AnyInferConfig(route: route).Dumps(),
                "Version 1 configuration serialized a route policy it cannot represent.");
        }

        return Task.CompletedTask;
    }

    private static ConfigException Refuse(string json)
    {
        try
        {
            AnyInferConfig.Loads(json);
        }
        catch (ConfigException failure)
        {
            return failure;
        }

        throw new InvalidOperationException($"Configuration {json} was accepted.");
    }
}
