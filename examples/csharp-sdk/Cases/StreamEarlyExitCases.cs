namespace AnyInfer.Examples.Cases;

/// <summary>Executes the early-exit and cancellation recipes published in the streaming guide.</summary>
internal static class StreamEarlyExitCases
{
    [ExampleCase("stream-early-exit.async-stop-cancels-request")]
    internal static async Task AsyncStopCancelsRequest()
    {
        var handler = new GuideScripts.StallingStreamHandler("Hello");
        var excerpt = await StreamEarlyExitExample.ReadAsync(GuideScripts.Instance(handler), ExampleSupport.Target, maxCharacters: 5);
        ExampleSupport.Require(excerpt is { Text: "Hello", Result: null }
            && handler.RequestCount == 1
            && handler.BodyReleased,
            "Stopping an asynchronous stream early did not release the in-flight response.");
    }

    [ExampleCase("stream-early-exit.async-reads-to-completion")]
    internal static async Task AsyncReadsToCompletion()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        var excerpt = await StreamEarlyExitExample.ReadAsync(GuideScripts.Instance(handler), ExampleSupport.Target, maxCharacters: 1000);
        ExampleSupport.Require(excerpt.Text == "hello"
            && excerpt.Result is { Text: "hello", FinishReason: "stop" }
            && handler.RequestCount == 1
            && handler.DisposeCount == 1,
            "A stream read to completion did not expose its terminal result.");
    }

    [ExampleCase("stream-early-exit.async-caller-cancellation")]
    internal static async Task AsyncCallerCancellation()
    {
        var handler = new GuideScripts.StallingStreamHandler("Hello");
        using var cancellation = new CancellationTokenSource();
        var reading = StreamEarlyExitExample.ReadAsync(
            GuideScripts.Instance(handler),
            ExampleSupport.Target,
            maxCharacters: 1000,
            cancellation.Token);
        await handler.Stalled.WaitAsync(TimeSpan.FromSeconds(30));
        cancellation.Cancel();
        var failure = await GuideScripts.ExpectThrowsAsync<OperationCanceledException>(
            () => reading,
            "Cancelling the caller token did not surface as OperationCanceledException.");
        ExampleSupport.Require(failure.CancellationToken == cancellation.Token && handler.BodyReleased,
            "Caller cancellation did not identify the caller token or release the response.");
    }

    [ExampleCase("stream-early-exit.client-dispose-cancels")]
    internal static async Task ClientDisposeCancels()
    {
        var handler = new GuideScripts.StallingStreamHandler("Hello");
        var client = new AsyncClient([GuideScripts.Instance(handler)]);
        var stream = client.StreamAsync("Explain TCP slow start.", target: ExampleSupport.Target);
        var reading = StreamEventsExample.LogAsync(stream);
        await handler.Stalled.WaitAsync(TimeSpan.FromSeconds(30));
        await client.DisposeAsync();
        await GuideScripts.ExpectThrowsAsync<OperationCanceledException>(
            () => reading,
            "Disposing the client did not cancel its open stream.");
        ExampleSupport.Require(handler.BodyReleased, "Disposing the client did not release the in-flight response.");
        await stream.DisposeAsync();
    }

    [ExampleCase("stream-early-exit.sync-starts-on-create")]
    internal static async Task SyncStartsOnCreate()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        using var client = new Client([GuideScripts.Instance(handler)]);
        using var stream = client.Stream("Say hello.", target: ExampleSupport.Target);
        var deadline = DateTime.UtcNow.AddSeconds(30);
        while (handler.RequestCount == 0 && DateTime.UtcNow < deadline)
        {
            await Task.Delay(10);
        }

        ExampleSupport.Require(handler.RequestCount == 1, "A synchronous stream did not start generating when it was created.");
        ExampleSupport.Require(stream.Collect().Text == "hello", "The eagerly started stream lost its result.");
    }

    [ExampleCase("stream-early-exit.sync-stop-cancels-generation")]
    internal static Task SyncStopCancelsGeneration()
    {
        var handler = new GuideScripts.StallingStreamHandler("Hello");
        var excerpt = StreamEarlyExitExample.Read(GuideScripts.Instance(handler), ExampleSupport.Target, maxCharacters: 5);
        ExampleSupport.Require(excerpt is { Text: "Hello", Result: null }
            && handler.RequestCount == 1
            && handler.BodyReleased,
            "Stopping a synchronous stream early did not stop its generation.");
        return Task.CompletedTask;
    }

    [ExampleCase("stream-early-exit.sync-reads-to-completion")]
    internal static Task SyncReadsToCompletion()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        var excerpt = StreamEarlyExitExample.Read(GuideScripts.Instance(handler), ExampleSupport.Target, maxCharacters: 1000);
        ExampleSupport.Require(excerpt is { Text: "hello", Result.Text: "hello" }
            && handler.RequestCount == 1
            && handler.DisposeCount == 1,
            "A synchronous stream read to completion lost its terminal result.");
        return Task.CompletedTask;
    }

    [ExampleCase("stream-early-exit.sync-collect")]
    internal static Task SyncCollect()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        using var client = new Client([GuideScripts.Instance(handler)]);
        var stream = client.Stream("Say hello.", target: ExampleSupport.Target);
        var result = stream.Collect();
        ExampleSupport.Require(result.Text == "hello" && ReferenceEquals(result, stream.Result),
            "Collect did not return the stream's terminal result.");
        GuideScripts.ExpectThrows<ObjectDisposedException>(() => stream.GetEnumerator(), "A collected synchronous stream was enumerated again.");
        return Task.CompletedTask;
    }
}
