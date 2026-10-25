using System.Runtime.CompilerServices;
using AnyInfer.Providers;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the provider-run tool recipe against built-in and application-owned descriptors.</summary>
internal static class ServerToolCases
{
    /// <summary>The built-in chat adapter refuses a server-side tool before sending, so the recipe asks again plainly.</summary>
    [ExampleCase("server-tools.refused-by-built-in-chat")]
    internal static async Task RefusedByBuiltInChat()
    {
        var transport = new RecipeChatHandler("Paris");
        await using (var client = new AsyncClient([ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl), transport)]))
        {
            var observation = await ServerToolExample.AskAsync(client, ExampleSupport.Target, "What is the capital of France?");
            ExampleSupport.Require(
                observation is { SearchOffered: false, Searches: 0 }
                && observation.Answer.Text == "Paris"
                && observation.Answer.ServerToolUses.Count == 0,
                "The built-in chat adapter did not refuse the server-side tool and answer the plain request.");
            ExampleSupport.Require(
                transport.Requests == 1
                && !transport.Bodies[0].TryGetProperty("tools", out _)
                && !transport.Bodies[0].TryGetProperty("web_search_options", out _),
                "The refused server-side tool reached the wire, or the plain request was not sent exactly once.");

            var refusal = await RecipeSupport.CaptureAsync(() => client.GenerateAsync(new GenerationRequest(
                [Message.User("What is the capital of France?")],
                new Route([ExampleSupport.Target]),
                serverTools: [new ServerToolSpec("web_search")])));
            ExampleSupport.Require(
                refusal is AllTargetsFailedException { Attempts.Count: 1 } exhausted
                && exhausted.Attempts[0].Error is UnsupportedInputException
                && transport.Requests == 1,
                "A server-side tool request did not fail with AllTargetsFailedException over UnsupportedInputException before dispatch.");
        }

        ExampleSupport.Require(transport.Disposals == 1, "The client did not dispose its transport once.");
    }

    /// <summary>A descriptor that declares web_search receives the tool and reports how often it ran.</summary>
    [ExampleCase("server-tools.application-descriptor")]
    internal static async Task ApplicationDescriptor()
    {
        var adapter = new RecipeSearchAdapter();
        var registry = new ProviderRegistry(
        [
            new ProviderDescriptor(
                "search-gateway",
                "Search gateway",
                (_, _) => new ValueTask<IAsyncDisposable>(adapter),
                serverTools: ["web_search"]),
        ]);
        await using (var client = new AsyncClient([ProviderSettings.Of("search-gateway")], registry: registry))
        {
            var observation = await ServerToolExample.AskAsync(client, "search-gateway:demo", "What changed today?");
            ExampleSupport.Require(
                observation is { SearchOffered: true, Searches: 2 }
                && observation.Answer.Text == "Here is what changed."
                && observation.Answer.ServerToolUses.Single() is { Kind: "web_search", Uses: 2 },
                "The application-owned descriptor did not report the provider-run searches.");
            ExampleSupport.Require(
                adapter.Calls == 1
                && adapter.ServerTools.Single() is { Kind: "web_search", MaxUses: 2 },
                "The adapter did not receive the server-side tool declaration exactly once.");
        }

        ExampleSupport.Require(adapter.Disposals == 1, "The client did not dispose the application adapter once.");
        var invalid = RecipeSupport.Capture(() => _ = new ServerToolSpec("file_search"));
        ExampleSupport.Require(invalid is ArgumentException, "An unknown server-side tool kind was accepted.");
    }
}

/// <summary>An application adapter that answers once and reports two provider-run searches.</summary>
internal sealed class RecipeSearchAdapter : IProviderAdapter
{
    /// <summary>Gets how many generations the adapter ran.</summary>
    public int Calls { get; private set; }

    /// <summary>Gets how many times the adapter was disposed.</summary>
    public int Disposals { get; private set; }

    /// <summary>Gets the server-side tools the last request declared.</summary>
    public IReadOnlyList<ServerToolSpec> ServerTools { get; private set; } = [];

    public async IAsyncEnumerable<AdapterEvent> GenerateAsync(
        WireRequest request,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        Calls++;
        ServerTools = request.ServerTools;
        await Task.Yield();
        cancellationToken.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta("Here is what changed.");
        yield return new AdapterFinal(
            "stop",
            new Usage(InputTokens: 4, OutputTokens: 5),
            serverToolUses: [new ServerToolUse("web_search", 2)]);
    }

    public ValueTask DisposeAsync()
    {
        Disposals++;
        return ValueTask.CompletedTask;
    }
}
