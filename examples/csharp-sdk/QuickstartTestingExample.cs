using System.Net;
using System.Text;
using System.Text.Json;
using AnyInfer;

namespace AnyInfer.Examples;

/// <summary>An application test of the quickstart call that needs no network, server, or API key.</summary>
public static class QuickstartTestingExample
{
    /// <summary>Runs the quickstart call over a scripted transport and checks what the application sees.</summary>
    /// <returns>The described result.</returns>
    /// <exception cref="InvalidOperationException">
    /// The call did not return the scripted reply, or the client did not send exactly one request and
    /// dispose the transport exactly once.
    /// </exception>
    public static async Task<string> RunOfflineAsync()
    {
        var transport = new ScriptedChatHandler("Mars", inputTokens: 9, outputTokens: 1);
        var settings = ProviderSettings.Of(
            "openai-compat",
            baseUrl: "http://127.0.0.1:11434/v1",
            transport: transport);

        var result = await QuickstartExample.FirstCallAsync(settings, "openai-compat:test-model");

        // The client owned the handler: one request went through it, and disposing the client disposed it.
        if (result.Text != "Mars" || transport.Requests != 1 || transport.Disposals != 1)
        {
            throw new InvalidOperationException("The quickstart call did not use the scripted transport as expected.");
        }

        return QuickstartExample.Describe(result);
    }
}

/// <summary>A test helper that answers every buffered OpenAI-compatible chat request with one reply.</summary>
/// <param name="reply">The assistant text every response carries.</param>
/// <param name="inputTokens">The prompt token count each response reports.</param>
/// <param name="outputTokens">The completion token count each response reports.</param>
public sealed class ScriptedChatHandler(string reply, int inputTokens = 1, int outputTokens = 1) : HttpMessageHandler
{
    /// <summary>Gets how many requests the handler answered.</summary>
    public int Requests { get; private set; }

    /// <summary>Gets how many times the handler was disposed.</summary>
    public int Disposals { get; private set; }

    /// <inheritdoc />
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Requests++;
        var body = JsonSerializer.Serialize(new
        {
            choices = new[] { new { message = new { content = reply }, finish_reason = "stop" } },
            usage = new
            {
                prompt_tokens = inputTokens,
                completion_tokens = outputTokens,
                total_tokens = inputTokens + outputTokens,
            },
        });
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        });
    }

    /// <inheritdoc />
    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Disposals++;
        }

        base.Dispose(disposing);
    }
}
