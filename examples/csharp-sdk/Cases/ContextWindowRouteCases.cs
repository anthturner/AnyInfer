using AnyInfer.Capabilities;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the context-window fallback route recipe.</summary>
internal static class ContextWindowRouteCases
{
    private static readonly string LongPrompt = string.Join(' ', Enumerable.Repeat("context", 400));

    /// <summary>A short prompt stays on the usual target; a long one is gated before dispatch and served by the large target.</summary>
    [ExampleCase("context-window-route.fallback")]
    internal static async Task Fallback()
    {
        var usual = new RecipeChatHandler("short answer");
        var large = new RecipeChatHandler("long answer");
        var shortResult = await ContextWindowRouteExample.GenerateAsync(
            Providers(usual, large), Windows(usualWindow: 64, largeWindow: 200_000), "usual:demo", "large:demo", "Say hello.");
        ExampleSupport.Require(
            shortResult.Text == "short answer" && shortResult.Target is { ProviderId: "usual" } && usual.Requests == 1 && large.Requests == 0,
            "A prompt that fits the usual window did not stay on the usual target.");

        usual = new RecipeChatHandler("short answer");
        large = new RecipeChatHandler("long answer");
        var longResult = await ContextWindowRouteExample.GenerateAsync(
            Providers(usual, large), Windows(usualWindow: 64, largeWindow: 200_000), "usual:demo", "large:demo", LongPrompt);
        ExampleSupport.Require(
            longResult.Text == "long answer"
            && longResult.Target is { ProviderId: "large", Model: "demo" }
            && longResult.Attempts.Count == 2
            && longResult.Attempts[0] is { Outcome: "failed", Error: ContextLengthException }
            && longResult.Attempts[1].Outcome == "ok"
            && usual.Requests == 0
            && large.Requests == 1
            && usual.Disposals == 1
            && large.Disposals == 1,
            "A prompt over the usual window was dispatched to it, or did not fall back to the context-window target.");
    }

    /// <summary>When neither window fits, every attempt is refused before dispatch.</summary>
    [ExampleCase("context-window-route.no-window-fits")]
    internal static async Task NoWindowFits()
    {
        var usual = new RecipeChatHandler();
        var large = new RecipeChatHandler();
        var failure = await RecipeSupport.CaptureAsync(() => ContextWindowRouteExample.GenerateAsync(
            Providers(usual, large), Windows(usualWindow: 64, largeWindow: 128), "usual:demo", "large:demo", LongPrompt));
        ExampleSupport.Require(
            failure is AllTargetsFailedException { Attempts.Count: 2 } exhausted
            && exhausted.Attempts.All(static attempt => attempt.Error is ContextLengthException)
            && usual.Requests == 0
            && large.Requests == 0,
            "A prompt over every trusted window was dispatched, or did not fail with AllTargetsFailedException.");
    }

    private static ProviderSettings[] Providers(HttpMessageHandler usual, HttpMessageHandler large) =>
    [
        ProviderSettings.Of("openai-compat", ExampleSupport.BaseUrl, transport: usual, alias: "usual"),
        ProviderSettings.Of("openai-compat", ExampleSupport.BaseUrl, transport: large, alias: "large"),
    ];

    private static Dictionary<string, IReadOnlyDictionary<string, ModelCapabilities>> Windows(int usualWindow, int largeWindow) => new()
    {
        ["usual"] = new Dictionary<string, ModelCapabilities>
        {
            ["demo"] = new(contextWindow: new Sourced<int>(usualWindow, Provenance.Override)),
        },
        ["large"] = new Dictionary<string, ModelCapabilities>
        {
            ["demo"] = new(contextWindow: new Sourced<int>(largeWindow, Provenance.Override)),
        },
    };
}
