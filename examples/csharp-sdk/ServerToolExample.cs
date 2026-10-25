namespace AnyInfer.Examples;

/// <summary>Requests a provider-run web search and reads how many searches the provider reported.</summary>
public static class ServerToolExample
{
    // --8<-- [start:ask]
    /// <summary>
    /// Asks a question with a provider-run web search allowed, and asks again without it when no target on
    /// the route can run the search.
    /// </summary>
    /// <param name="client">A client the caller owns and disposes.</param>
    /// <param name="target">A <c>provider:model</c> target.</param>
    /// <param name="question">The user's question.</param>
    /// <param name="cancellationToken">Cancels either request.</param>
    /// <returns>The answer and the number of searches the provider reported running.</returns>
    public static async Task<ServerToolObservation> AskAsync(
        AsyncClient client,
        string target,
        string question,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);
        var request = new GenerationRequest(
            [Message.User(question)],
            new Route([target]),
            serverTools: [new ServerToolSpec("web_search", maxUses: 2)]);
        try
        {
            var answer = await client.GenerateAsync(request, cancellationToken);
            var searches = answer.ServerToolUses
                .Where(static use => use.Kind == "web_search")
                .Sum(static use => use.Uses);
            return new ServerToolObservation(answer, searches, SearchOffered: true);
        }
        catch (AllTargetsFailedException failure)
            when (failure.Attempts.All(static attempt => attempt.Error is UnsupportedInputException))
        {
            // Every target refused the server-side tool before its provider was called.
            var answer = await client.GenerateAsync(question, target: target, cancellationToken: cancellationToken);
            return new ServerToolObservation(answer, Searches: 0, SearchOffered: false);
        }
    }
    // --8<-- [end:ask]
}

/// <summary>Contains one answer, the provider-reported search count, and whether the search was offered.</summary>
public sealed record ServerToolObservation(Generation Answer, long Searches, bool SearchOffered);
