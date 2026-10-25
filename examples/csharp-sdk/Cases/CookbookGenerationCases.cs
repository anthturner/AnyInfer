using System.Net;
using AnyInfer.Config;

namespace AnyInfer.Examples.Cases;

/// <summary>Runs the configuration-driven release-notes summarizer offline.</summary>
/// <remarks>
/// The shipped configuration is written to a file and read with <see cref="AnyInferConfig.Load"/>, then
/// each configured instance receives a scripted transport; routing, retry, repair, validation and the
/// health gate are the SDK's own.
/// </remarks>
internal static class CookbookGenerationCases
{
    private static readonly CookbookReleaseNote[] Notes =
    [
        new("r-101", "Cold starts now reuse the model cache."),
        new("r-102", "Fixes token refresh races."),
    ];

    [ExampleCase("cookbook.generation.fallback-and-repair")]
    internal static async Task FallbackAndRepair()
    {
        var cerebras = new CookbookScriptedHandler(
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable),
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable));
        var local = new CookbookScriptedHandler(
            CookbookReplies.Chat("""{"headline":"Faster cold starts","risk":"unknown","topics":[]}""", 120, 30),
            CookbookReplies.Chat("""{"headline":"Faster cold starts","risk":"low","topics":["startup","cache"]}""", 150, 25),
            CookbookReplies.Chat("""{"headline":"Token refresh fix","risk":"medium","topics":["auth"]}""", 90, 20));
        var output = new StringWriter();
        IReadOnlyList<CookbookSummaryOutcome> outcomes;
        using (new CookbookEnvironment(("CEREBRAS_API_KEY", "offline-cerebras-key")))
        {
            outcomes = await CookbookGenerationExample.RunAsync(
                Offline(LoadShipped(), ("cerebras", cerebras), ("local", local)), Notes, output);
        }

        var first = outcomes[0];
        ExampleSupport.Require(outcomes.Count == 2
            && first.Summary is { Headline: "Faster cold starts", Risk: "low" } summary
            && summary.Topics.SequenceEqual(["startup", "cache"])
            && first.ServedBy == "local:qwen3-8b"
            && first.Mechanism == "prompt"
            && first.Repairs == 1
            && first.Usage is { InputTokens: 150, OutputTokens: 25, TotalTokens: 175, CostUsd: null }
            && first.FailureCategory is null
            && first.Attempts.SequenceEqual([
                "cerebras:gpt-oss-120b: retried (ProviderUnavailableException, HTTP 503)",
                "cerebras:gpt-oss-120b: failed (ProviderUnavailableException, HTTP 503)",
                "local:qwen3-8b: ok",
            ]),
            "The first release did not fall back after the primary's retry, or lost its repair or usage facts.");
        ExampleSupport.Require(outcomes[1] is { Summary.Risk: "medium", Repairs: 0, Usage.TotalTokens: 110 } second
            && second.Attempts.SequenceEqual(["cerebras:gpt-oss-120b: skipped_unhealthy", "local:qwen3-8b: ok"]),
            "The health gate did not skip the primary that had just failed.");

        // The primary resolved its env:// credential; the keyless local server received none.
        ExampleSupport.Require(cerebras.Requests.Count == 2
            && cerebras.Requests.All(static request => request.Uri.AbsoluteUri == "https://api.cerebras.ai/v1/chat/completions"
                && request.Authorization == "Bearer offline-cerebras-key")
            && local.Requests.Count == 3
            && local.Requests.All(static request => request.Uri.AbsoluteUri == "http://127.0.0.1:8000/v1/chat/completions"
                && request.Authorization is null),
            "The configured endpoints or credential references were not used as written.");
        var repair = local.Requests[1].Json().GetProperty("messages").EnumerateArray().ToArray();
        ExampleSupport.Require(repair.Length == 4
            && repair[2].GetProperty("role").GetString() == "assistant"
            && repair[2].GetProperty("content").GetString()!.Contains("\"unknown\"", StringComparison.Ordinal)
            && local.Requests.All(static request => !request.Body.Contains("r-101", StringComparison.Ordinal)
                && request.Json().GetProperty("max_tokens").GetInt32() == 400),
            "The repair round trip or request options were not what the program asked for; metadata must stay local.");
        ExampleSupport.Require(output.ToString().Contains(
                "r-101: [low] Faster cold starts (via local:qwen3-8b, prompt, 1 repair(s), 175 tokens)", StringComparison.Ordinal)
            && cerebras.DisposeCount == 1
            && local.DisposeCount == 1,
            "The report was not written, or the client did not release each transport once.");
    }

    [ExampleCase("cookbook.generation.all-targets-failed")]
    internal static async Task AllTargetsFailed()
    {
        var cerebras = new CookbookScriptedHandler(
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable),
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable));
        var local = new CookbookScriptedHandler(
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable),
            CookbookReplies.Status(HttpStatusCode.ServiceUnavailable));
        var output = new StringWriter();
        IReadOnlyList<CookbookSummaryOutcome> outcomes;
        using (new CookbookEnvironment(("CEREBRAS_API_KEY", "offline-cerebras-key")))
        {
            outcomes = await CookbookGenerationExample.RunAsync(
                Offline(LoadShipped(), ("cerebras", cerebras), ("local", local)), Notes, output);
        }

        ExampleSupport.Require(outcomes[0] is { Summary: null, FailureCategory: "all_targets_failed" } first
            && first.Attempts.Count == 4
            && first.Attempts.All(static line => line.EndsWith("(ProviderUnavailableException, HTTP 503)", StringComparison.Ordinal))
            && outcomes[1] is { Summary: null, FailureCategory: "all_targets_failed" } second
            && second.Attempts.SequenceEqual(["cerebras:gpt-oss-120b: skipped_unhealthy", "local:qwen3-8b: skipped_unhealthy"])
            && cerebras.Requests.Count == 2
            && local.Requests.Count == 2
            && output.ToString().Contains("r-102: not summarized (all_targets_failed)", StringComparison.Ordinal),
            "An exhausted route was not reported per release, or the second release did not fail fast.");
    }

    [ExampleCase("cookbook.generation.schema-violation")]
    internal static async Task SchemaViolation()
    {
        var cerebras = new CookbookScriptedHandler(
            CookbookReplies.Chat("Here is your summary!"),
            CookbookReplies.Chat("""{"headline":""}"""),
            CookbookReplies.Chat("""{"headline":"Token refresh fix","risk":"high","topics":["auth"]}"""));
        var local = new CookbookScriptedHandler();
        var output = new StringWriter();
        IReadOnlyList<CookbookSummaryOutcome> outcomes;
        using (new CookbookEnvironment(("CEREBRAS_API_KEY", "offline-cerebras-key")))
        {
            outcomes = await CookbookGenerationExample.RunAsync(
                Offline(LoadShipped(), ("cerebras", cerebras), ("local", local)), Notes, output);
        }

        // A response that still fails validation after the repair budget does not move to the next target.
        ExampleSupport.Require(outcomes[0] is { Summary: null, FailureCategory: "schema_violation" }
            && outcomes[1] is { Summary.Risk: "high", ServedBy: "cerebras:gpt-oss-120b", Repairs: 0 }
            && cerebras.Requests.Count == 3
            && local.Requests.Count == 0
            && output.ToString().Contains("r-101: not summarized (schema_violation: ", StringComparison.Ordinal),
            "An exhausted repair budget was not reported as a schema violation on the primary.");
    }

    [ExampleCase("cookbook.generation.missing-credential")]
    internal static async Task MissingCredential()
    {
        var cerebras = new CookbookScriptedHandler();
        var local = new CookbookScriptedHandler();
        Exception? failure = null;
        using (new CookbookEnvironment(("CEREBRAS_API_KEY", null)))
        {
            try
            {
                await CookbookGenerationExample.RunAsync(
                    Offline(LoadShipped(), ("cerebras", cerebras), ("local", local)), Notes, new StringWriter());
            }
            catch (CredentialException exception)
            {
                failure = exception;
            }
        }

        // Loading never resolved the reference; the first request that needed it did, and nothing was sent.
        ExampleSupport.Require(failure is CredentialException
            && cerebras.Requests.Count == 0
            && local.Requests.Count == 0,
            "An unset credential reference did not stop the program before any request.");
    }

    private static AnyInferConfig LoadShipped()
    {
        var path = Path.Combine(Path.GetTempPath(), $"anyinfer-cookbook-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, CookbookGenerationExample.Configuration);
        try
        {
            return AnyInferConfig.Load(path);
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static AnyInferConfig Offline(AnyInferConfig shipped, params (string Instance, HttpMessageHandler Transport)[] transports)
    {
        var byInstance = transports.ToDictionary(static item => item.Instance, static item => item.Transport, StringComparer.Ordinal);
        ExampleSupport.Require(shipped.Providers.Select(static provider => provider.InstanceId).SequenceEqual(["cerebras", "local"])
            && shipped.Route?.Targets.SequenceEqual(["cerebras:gpt-oss-120b", "local:qwen3-8b"]) == true
            && shipped.Repair?.MaxAttempts == 1,
            "The shipped configuration did not load as documented.");
        return new AnyInferConfig(
            shipped.Providers.Select(provider => ExampleSupport.WithTransport(provider, byInstance[provider.InstanceId])),
            shipped.Route,
            shipped.Repair,
            cache: shipped.Cache,
            operationRoutes: shipped.OperationRoutes);
    }
}
