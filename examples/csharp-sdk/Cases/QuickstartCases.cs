using System.Net;
using System.Text;
using System.Text.Json;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts the quickstart's settings, first call, cancellation, and lifetimes.</summary>
internal static class QuickstartCases
{
    private const string LocalTarget = "openai-compat:qwen3:8b";
    private const string KeyVariable = "ANYINFER_QUICKSTART_OFFLINE_KEY";

    /// <summary>The buffered call reads text and usage and sends one keyless loopback request.</summary>
    [ExampleCase("quickstart.first-call")]
    internal static async Task FirstCall()
    {
        var transport = new QuickstartRecordingHandler();
        var result = await QuickstartExample.FirstCallAsync(
            ExampleSupport.WithTransport(QuickstartExample.LocalServer(), transport),
            LocalTarget);

        ExampleSupport.Require(
            result.Text == "Mars"
            && result.FinishReason == "stop"
            && result.Usage is { InputTokens: 9, OutputTokens: 1, TotalTokens: 10 }
            && result.Target is { ProviderId: "openai-compat", Model: "qwen3:8b" }
            && result.Attempts.Count == 1
            && QuickstartExample.Describe(result) == "Mars (9 input + 1 output tokens)",
            "The quickstart call did not return the scripted text, target, and usage.");
        ExampleSupport.Require(
            transport.Requests == 1
            && transport.Disposals == 1
            && transport.Uri == "http://127.0.0.1:11434/v1/chat/completions"
            && transport.Authorization is null
            && transport.Model == "qwen3:8b"
            && transport.Prompt == "Name one planet in the solar system."
            && transport.Streamed == false,
            "The quickstart call did not send one keyless loopback chat request and dispose its transport once.");
        ExampleSupport.Require(
            QuickstartExample.Describe(new Generation("Mars")) == "Mars (no usage reported)",
            "The quickstart description did not report missing usage.");
    }

    /// <summary>An env:// key resolves at the first call; a missing one fails before any request.</summary>
    [ExampleCase("quickstart.hosted-key-reference")]
    internal static async Task HostedKeyReference()
    {
        var settings = QuickstartExample.Hosted(ExampleSupport.BaseUrl, $"env://{KeyVariable}");
        try
        {
            Environment.SetEnvironmentVariable(KeyVariable, null);
            var missing = new QuickstartRecordingHandler();
            var failed = false;
            try
            {
                await QuickstartExample.FirstCallAsync(ExampleSupport.WithTransport(settings, missing), "openai-compat:demo");
            }
            catch (CredentialException)
            {
                failed = true;
            }

            ExampleSupport.Require(
                failed && missing.Requests == 0 && missing.Disposals == 1,
                "A missing key reference did not fail with CredentialException before sending a request.");

            Environment.SetEnvironmentVariable(KeyVariable, "offline-placeholder");
            var present = new QuickstartRecordingHandler();
            var result = await QuickstartExample.FirstCallAsync(ExampleSupport.WithTransport(settings, present), "openai-compat:demo");
            ExampleSupport.Require(
                result.Text == "Mars"
                && present.Authorization == "Bearer offline-placeholder"
                && present.Uri == "https://offline.example/v1/chat/completions"
                && present.Requests == 1
                && present.Disposals == 1,
                "A resolved key reference was not sent as a bearer token.");
        }
        finally
        {
            Environment.SetEnvironmentVariable(KeyVariable, null);
        }
    }

    /// <summary>A cancelled token surfaces as OperationCanceledException and sends nothing.</summary>
    [ExampleCase("quickstart.cancellation")]
    internal static async Task Cancellation()
    {
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();

        var asyncTransport = new QuickstartRecordingHandler();
        var asyncFailure = await CaptureAsync(() => QuickstartExample.FirstCallAsync(
            ExampleSupport.WithTransport(QuickstartExample.LocalServer(), asyncTransport),
            LocalTarget,
            cancelled.Token));
        ExampleSupport.Require(
            asyncFailure is not null
            && asyncFailure.GetType() == typeof(OperationCanceledException)
            && ((OperationCanceledException)asyncFailure).CancellationToken == cancelled.Token
            && asyncTransport.Requests == 0
            && asyncTransport.Disposals == 1,
            "A cancelled asynchronous call did not throw OperationCanceledException before sending a request.");

        var syncTransport = new QuickstartRecordingHandler();
        Exception? syncFailure = null;
        try
        {
            QuickstartExample.FirstCall(
                ExampleSupport.WithTransport(QuickstartExample.LocalServer(), syncTransport),
                LocalTarget,
                cancelled.Token);
        }
        catch (Exception exception)
        {
            syncFailure = exception;
        }

        ExampleSupport.Require(
            syncFailure is not null
            && syncFailure.GetType() == typeof(OperationCanceledException)
            && syncTransport.Requests == 0
            && syncTransport.Disposals == 1,
            "A cancelled synchronous call did not throw OperationCanceledException directly before sending a request.");
    }

    /// <summary>A caller deadline cancels the in-flight request; a call that finishes first is returned.</summary>
    [ExampleCase("quickstart.deadline")]
    internal static async Task Deadline()
    {
        var hanging = new QuickstartRecordingHandler(hang: true);
        var expired = await QuickstartExample.FirstCallWithDeadlineAsync(
            ExampleSupport.WithTransport(QuickstartExample.LocalServer(), hanging),
            LocalTarget,
            TimeSpan.FromMilliseconds(200));
        ExampleSupport.Require(
            expired is null
            && hanging.Requests == 1
            && hanging.CancelledRequests == 1
            && hanging.Disposals == 1,
            "The deadline did not cancel the single in-flight request and dispose the transport.");

        var prompt = new QuickstartRecordingHandler();
        var completed = await QuickstartExample.FirstCallWithDeadlineAsync(
            ExampleSupport.WithTransport(QuickstartExample.LocalServer(), prompt),
            LocalTarget,
            TimeSpan.FromSeconds(30));
        ExampleSupport.Require(
            completed is { Text: "Mars" } && prompt.Requests == 1 && prompt.Disposals == 1,
            "A call that finished before its deadline did not return its result.");
    }

    /// <summary>An exhausted per-attempt timeout is retried and ends in AllTargetsFailedException.</summary>
    [ExampleCase("quickstart.attempt-timeout")]
    internal static async Task AttemptTimeout()
    {
        var hanging = new QuickstartRecordingHandler(hang: true);
        var settings = ProviderSettings.Of(
            "openai-compat",
            baseUrl: "http://127.0.0.1:11434/v1",
            timeoutS: 0.1,
            transport: hanging);
        var failure = await CaptureAsync(() => QuickstartExample.FirstCallAsync(settings, LocalTarget));
        ExampleSupport.Require(
            failure is AllTargetsFailedException { Attempts.Count: 2 } exhausted
            && exhausted.Attempts[0].Outcome == "retried"
            && exhausted.Attempts[1].Outcome == "failed"
            && exhausted.Attempts.All(static attempt => attempt.Error is ProviderException { Retryable: true })
            && hanging.Requests == 2
            && hanging.Disposals == 1,
            "A per-attempt timeout was not retried and reported as AllTargetsFailedException.");

        var perCall = new QuickstartRecordingHandler(hang: true);
        await using (var client = new AsyncClient([ExampleSupport.WithTransport(QuickstartExample.LocalServer(), perCall)]))
        {
            var callFailure = await CaptureAsync(() => client.GenerateAsync(
                "Name one planet in the solar system.",
                target: LocalTarget,
                timeoutS: 0.1));
            ExampleSupport.Require(
                callFailure is AllTargetsFailedException { Attempts.Count: 2 } && perCall.Requests == 2,
                "A per-call attempt timeout was not retried and reported as AllTargetsFailedException.");
        }

        ExampleSupport.Require(perCall.Disposals == 1, "The per-call timeout client did not dispose its transport once.");
    }

    /// <summary>Both lifetimes dispose the transport once; a disposed client refuses new calls.</summary>
    [ExampleCase("quickstart.disposal")]
    internal static async Task Disposal()
    {
        var syncTransport = new QuickstartRecordingHandler();
        var syncResult = QuickstartExample.FirstCall(
            ExampleSupport.WithTransport(QuickstartExample.LocalServer(), syncTransport),
            LocalTarget);
        ExampleSupport.Require(
            syncResult.Text == "Mars"
            && syncResult.Usage is { InputTokens: 9, OutputTokens: 1 }
            && syncTransport.Requests == 1
            && syncTransport.Disposals == 1,
            "The synchronous call did not return its result and dispose its transport once.");

        var unused = new QuickstartRecordingHandler();
        var client = new AsyncClient([ExampleSupport.WithTransport(QuickstartExample.LocalServer(), unused)]);
        await client.DisposeAsync();
        await client.DisposeAsync();
        var afterDispose = await CaptureAsync(() => client.GenerateAsync("Name one planet in the solar system.", target: LocalTarget));
        ExampleSupport.Require(
            unused.Disposals == 1 && unused.Requests == 0 && afterDispose is ObjectDisposedException,
            "Disposing an asynchronous client twice did not dispose its transport once and refuse later calls.");

        var inFlight = new QuickstartRecordingHandler(hang: true);
        var busy = new AsyncClient([ExampleSupport.WithTransport(QuickstartExample.LocalServer(), inFlight)]);
        var running = busy.GenerateAsync("Name one planet in the solar system.", target: LocalTarget);
        await inFlight.Started.WaitAsync(TimeSpan.FromSeconds(30));
        await busy.DisposeAsync();
        var interrupted = await CaptureAsync(() => running);
        ExampleSupport.Require(
            interrupted is OperationCanceledException
            && inFlight.Requests == 1
            && inFlight.CancelledRequests == 1
            && inFlight.Disposals == 1,
            "Disposing a client did not cancel its running call and then dispose its transport once.");

        var syncUnused = new QuickstartRecordingHandler();
        var syncClient = new Client([ExampleSupport.WithTransport(QuickstartExample.LocalServer(), syncUnused)]);
        syncClient.Dispose();
        syncClient.Dispose();
        Exception? syncAfterDispose = null;
        try
        {
            syncClient.Generate("Name one planet in the solar system.", target: LocalTarget);
        }
        catch (Exception exception)
        {
            syncAfterDispose = exception;
        }

        ExampleSupport.Require(
            syncUnused.Disposals == 1 && syncUnused.Requests == 0 && syncAfterDispose is ObjectDisposedException,
            "Disposing a synchronous client twice did not dispose its transport once and refuse later calls.");

        var shared = new QuickstartRecordingHandler();
        Exception? sharedFailure = null;
        try
        {
            await using var rejected = new AsyncClient(
            [
                ExampleSupport.WithTransport(QuickstartExample.LocalServer(), shared),
                ExampleSupport.WithTransport(ProviderSettings.Of("openai-compat", baseUrl: "http://127.0.0.1:1234/v1", alias: "second-server"), shared),
            ]);
        }
        catch (Exception exception)
        {
            sharedFailure = exception;
        }

        ExampleSupport.Require(
            sharedFailure is ConfigException && shared.Disposals == 0 && shared.Requests == 0,
            "One transport shared by two provider instances was not rejected before ownership passed.");
        shared.Dispose();
    }

    /// <summary>The application test helper runs the quickstart call offline.</summary>
    [ExampleCase("quickstart.offline-test")]
    internal static async Task OfflineTest()
    {
        var described = await QuickstartTestingExample.RunOfflineAsync();
        ExampleSupport.Require(
            described == "Mars (9 input + 1 output tokens)",
            "The offline quickstart test did not describe the scripted result.");

        var helper = new ScriptedChatHandler("Venus");
        var settings = ProviderSettings.Of("openai-compat", baseUrl: "http://127.0.0.1:11434/v1", transport: helper);
        var reply = QuickstartExample.FirstCall(settings, "openai-compat:test-model");
        ExampleSupport.Require(
            reply.Text == "Venus"
            && reply.Usage is { InputTokens: 1, OutputTokens: 1, TotalTokens: 2 }
            && helper.Requests == 1
            && helper.Disposals == 1,
            "The scripted chat handler did not answer the synchronous facade with its default usage.");
    }

    private static async Task<Exception?> CaptureAsync(Func<Task> call)
    {
        try
        {
            await call();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }
}

/// <summary>Records each chat request and answers it, or waits for its cancellation.</summary>
internal sealed class QuickstartRecordingHandler(bool hang = false) : HttpMessageHandler
{
    private readonly TaskCompletionSource _started = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public Task Started => _started.Task;
    public int Requests { get; private set; }
    public int CancelledRequests { get; private set; }
    public int Disposals { get; private set; }
    public string? Uri { get; private set; }
    public string? Authorization { get; private set; }
    public string? Model { get; private set; }
    public string? Prompt { get; private set; }
    public bool? Streamed { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests++;
        Uri = request.RequestUri?.AbsoluteUri;
        Authorization = request.Headers.Authorization?.ToString();
        var body = request.Content is null ? "{}" : await request.Content.ReadAsStringAsync(cancellationToken);
        using (var document = JsonDocument.Parse(body))
        {
            var root = document.RootElement;
            Model = root.GetProperty("model").GetString();
            Prompt = root.GetProperty("messages")[0].GetProperty("content").GetString();
            Streamed = root.TryGetProperty("stream", out var stream) && stream.GetBoolean();
        }

        if (request.Method != HttpMethod.Post)
        {
            throw new InvalidOperationException("The quickstart sent an unexpected HTTP method.");
        }

        _started.TrySetResult();
        if (hang)
        {
            try
            {
                await Task.Delay(Timeout.Infinite, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                CancelledRequests++;
                throw;
            }
        }

        const string response = "{\"choices\":[{\"message\":{\"content\":\"Mars\"},\"finish_reason\":\"stop\"}],"
            + "\"usage\":{\"prompt_tokens\":9,\"completion_tokens\":1,\"total_tokens\":10}}";
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(response, Encoding.UTF8, "application/json"),
        };
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Disposals++;
        }

        base.Dispose(disposing);
    }
}
