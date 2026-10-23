namespace AnyInfer.Internal;

/// <summary>Runs one caller-authorized, sequential bounded tool conversation.</summary>
internal static class ToolLoop
{
    internal static async Task<Generation> RunAsync(
        GenerationRequest request,
        ToolRegistry registry,
        int maxRounds,
        Func<GenerationRequest, CancellationToken, Task<Generation>> generate,
        Func<CancellationToken, Task> checkpoint,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(registry);
        ArgumentNullException.ThrowIfNull(generate);
        ArgumentNullException.ThrowIfNull(checkpoint);
        var conversation = request.Messages.ToList();

        for (var round = 0; round < maxRounds; round++)
        {
            await checkpoint(cancellationToken).ConfigureAwait(false);
            var result = await generate(
                request.WithMessagesAndTools(conversation, registry.Specs),
                cancellationToken).ConfigureAwait(false);
            await checkpoint(cancellationToken).ConfigureAwait(false);
            if (result.FinishReason != "tool_calls" || result.ToolCalls.Count == 0)
            {
                return result;
            }

            var outputs = new List<ToolResult>(result.ToolCalls.Count);
            foreach (var call in result.ToolCalls)
            {
                await checkpoint(cancellationToken).ConfigureAwait(false);
                outputs.Add(await registry.DispatchAsync(call, cancellationToken).ConfigureAwait(false));
                await checkpoint(cancellationToken).ConfigureAwait(false);
            }

            conversation.Add(new Message("assistant", result.ToolCalls));
            foreach (var output in outputs)
            {
                conversation.Add(new Message("tool", [output]));
            }
        }

        throw new ToolLoopException(
            $"The tool loop ran {maxRounds} rounds without a final answer.",
            hint: "Raise maxRounds, or simplify the tools so the model converges.");
    }
}
