namespace AnyInfer.Examples;

/// <summary>Runs a registered-tool loop and handles the failures that end the loop.</summary>
public static class ToolFailureExample
{
    // --8<-- [start:loop-failure]
    /// <summary>Answers a stock question, or explains why the tool loop could not finish.</summary>
    public static async Task<string> AnswerAsync(
        ProviderSettings settings,
        string target,
        IReadOnlyDictionary<string, int> stock,
        int maxRounds = 8,
        CancellationToken cancellationToken = default)
    {
        await using var client = new AsyncClient([settings]);
        try
        {
            var generation = await client.RunToolsAsync(
                "How many ABC-1234 units are in stock?",
                [ToolDeclarationExample.Inventory(stock)],
                target: target,
                maxRounds: maxRounds,
                cancellationToken: cancellationToken);
            return generation.Text;
        }
        catch (ToolLoopException error)
        {
            // The model called an unregistered tool, or maxRounds ended with tool calls still pending.
            return $"The assistant could not finish: {error.Message} {error.Hint}";
        }
    }
    // --8<-- [end:loop-failure]
}
