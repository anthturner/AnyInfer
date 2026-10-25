using AnyInfer.Capabilities;
using AnyInfer.Config;
using AnyInfer.Providers;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the version 1 configuration-file recipe and its rejected blocks.</summary>
internal static class ConfigurationFileCases
{
    /// <summary>The document loads inertly; the rerank operation route and default route then serve both calls.</summary>
    [ExampleCase("configuration-file.accepted-blocks")]
    internal static async Task AcceptedBlocks()
    {
        var config = ConfigurationFileExample.Load(ConfigurationFileExample.Document);
        ExampleSupport.Require(
            config.FormatVersion == 1
            && config.Providers.Select(static provider => provider.InstanceId).SequenceEqual(["local-chat", "tei-embed", "tei-rerank"])
            && config.Route?.Targets.SequenceEqual(["local-chat:qwen3:8b"]) == true
            && config.OperationRoutes[InferenceOperation.Embedding].Targets.SequenceEqual(["tei-embed:BAAI/bge-small-en-v1.5"])
            && config.OperationRoutes[InferenceOperation.Rerank].Targets.SequenceEqual(["tei-rerank:BAAI/bge-reranker-base"])
            && config.Repair?.MaxAttempts == 1
            && config.Cache?.Mode == CacheMode.Auto,
            "The configuration document did not load every accepted block.");

        var chat = new RecipeChatHandler("Rivers carry water.");
        var embed = new RecipeTeiHandler();
        var rerank = new RecipeTeiHandler();
        var offline = new AnyInferConfig(
            config.Providers.Select(provider => ExampleSupport.WithTransport(provider, provider.InstanceId switch
            {
                "local-chat" => chat,
                "tei-embed" => embed,
                _ => rerank,
            })),
            config.Route,
            config.Repair,
            cache: config.Cache,
            operationRoutes: config.OperationRoutes);
        var answer = await ConfigurationFileExample.AnswerAsync(
            offline,
            "What carries water?",
            [new RerankDocument("road", "A road crosses the plain."), new RerankDocument("river", "A river carries water.")]);
        ExampleSupport.Require(
            answer.PassageId == "river"
            && answer.Answer.Text == "Rivers carry water."
            && answer.Answer.Target is { ProviderId: "local-chat", Model: "qwen3:8b" },
            "The configured routes did not rank the passages and answer from the best one.");
        ExampleSupport.Require(
            rerank.Paths.SequenceEqual(["/rerank"])
            && embed.Requests == 0
            && chat.Requests == 1
            && chat.Uris.Single() == "http://127.0.0.1:11434/v1/chat/completions"
            && chat.Bodies[0].GetProperty("model").GetString() == "qwen3:8b"
            && chat.Bodies[0].GetProperty("messages")[0].GetProperty("content").GetString()!.Contains("A river carries water.", StringComparison.Ordinal)
            && chat.Disposals == 1
            && rerank.Disposals == 1
            && embed.Disposals == 1,
            "The configured client did not send exactly the rerank and chat requests, or did not dispose each transport once.");
    }

    /// <summary>Unimplemented blocks and unknown keys fail at load with ConfigException.</summary>
    [ExampleCase("configuration-file.rejected-blocks")]
    internal static void RejectedBlocks()
    {
        foreach (var block in new[] { "observers", "context", "history", "mcp", "arena" })
        {
            var document = ConfigurationFileExample.Document.Replace(
                "\"format_version\": 1,",
                $"\"format_version\": 1, \"{block}\": {{}},",
                StringComparison.Ordinal);
            var failure = RecipeSupport.Capture(() => ConfigurationFileExample.Load(document));
            ExampleSupport.Require(
                failure is ConfigException { Message: var message }
                && message.Contains("anyinfer.json", StringComparison.Ordinal)
                && message.Contains(block, StringComparison.Ordinal),
                $"The unimplemented '{block}' block was not rejected at load with its source name.");
        }

        var generationRoute = ConfigurationFileExample.Document.Replace(
            "\"rerank\": [",
            "\"generation\": [\"local-chat:qwen3:8b\"], \"rerank\": [",
            StringComparison.Ordinal);
        ExampleSupport.Require(
            RecipeSupport.Capture(() => ConfigurationFileExample.Load(generationRoute)) is ConfigException,
            "An operation route other than embedding or rerank was accepted.");
        var version2 = ConfigurationFileExample.Document.Replace("\"format_version\": 1", "\"format_version\": 2", StringComparison.Ordinal);
        ExampleSupport.Require(
            RecipeSupport.Capture(() => ConfigurationFileExample.Load(version2)) is ConfigException,
            "An unsupported format version was accepted.");
    }
}
