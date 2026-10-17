using System.Numerics;
using AnyInfer.Json;
using AnyInfer.Providers;

namespace AnyInfer.Conformance;

/// <summary>Projects retained HTTP exchange and adapter facts without consulting fixture expectations.</summary>
internal static class TransportProjection
{
    internal static JsonObject Project(TransportRun run)
    {
        ArgumentNullException.ThrowIfNull(run);
        Validate(run);

        var requests = new List<JsonValue>(run.Exchanges.Count);
        foreach (var exchange in run.Exchanges)
        {
            requests.Add(new JsonObject([
                Property("method", String(exchange.Method)),
                Property("path", String(exchange.Path)),
                Property("headers", exchange.SemanticHeaders),
                Property("body", exchange.Body),
                Property("stream", new JsonBoolean(exchange.Stream)),
            ]));
        }

        var limits = new List<JsonValue>(run.WireRequests.Count);
        foreach (var request in run.WireRequests)
        {
            limits.Add(new JsonObject([
                Property("timeout_s", Number(request.TimeoutS)),
                Property("max_response_bytes", Integer(request.MaxResponseBytes)),
            ]));
        }

        var fields = new List<JsonProperty>
        {
            Property("status", String("observed")),
            Property("http_requests", new JsonArray(requests)),
            Property("wire_limits", new JsonArray(limits)),
        };
        if (run.Core is not null)
        {
            fields.Add(Property("core", Projection.Project(run.Core)));
        }
        else
        {
            fields.Add(Property("adapter_outcome", ProjectAdapterOutcome(run)));
        }

        return new JsonObject(fields);
    }

    private static void Validate(TransportRun run)
    {
        if (string.IsNullOrWhiteSpace(run.CaseId) || run.Input is null ||
            run.Input.Kind is not ("adapter" or "core_http") ||
            run.AdapterCallCount != run.WireRequests.Count ||
            run.ActualHttpRequestCount != run.Exchanges.Count ||
            run.AdapterCallCount != run.ActualHttpRequestCount ||
            run.RemainingResponses != 0 || !run.HandlerDisposed)
        {
            throw new ObservationUnavailableException("transport run facts are incomplete or inconsistent");
        }

        if (run.Input.Kind == "core_http")
        {
            if (run.Core is null || run.DirectEvents.Count != 0 ||
                !ReferenceEquals(run.Core.Input, run.Input) ||
                !string.Equals(run.Core.CaseId, run.CaseId, StringComparison.Ordinal) ||
                run.Core.Capture.Entries.Count != run.WireRequests.Count)
            {
                throw new ObservationUnavailableException("transport core run facts are incomplete or inconsistent");
            }
        }
        else if (run.Core is not null)
        {
            throw new ObservationUnavailableException("direct transport run retained a core execution");
        }

        for (var index = 0; index < run.Exchanges.Count; index++)
        {
            var exchange = run.Exchanges[index];
            if (exchange.Ordinal != index ||
                !ReferenceEquals(exchange.BoundWireRequest, run.WireRequests[index]) ||
                !exchange.ResponseCreated || !exchange.ContentCreated ||
                !exchange.ResponseDisposed || !exchange.ContentDisposed ||
                exchange.CreatedStreamCount != exchange.DisposedStreamCount ||
                exchange.AutomaticSerializationRequested)
            {
                throw new ObservationUnavailableException("transport exchange provenance or resources are inconsistent");
            }

            if (run.Core is not null && !ReferenceEquals(exchange.BoundWireRequest, run.Core.Capture.Entries[index].Request))
            {
                throw new ObservationUnavailableException("transport exchange is not bound to the captured core entry");
            }
        }
    }

    private static JsonObject ProjectAdapterOutcome(TransportRun run)
    {
        var events = new List<JsonValue>(run.DirectEvents.Count);
        foreach (var adapterEvent in run.DirectEvents)
        {
            events.Add(adapterEvent switch
            {
                AdapterTextDelta text => new JsonObject([Property("text_delta", new JsonObject([Property("text", String(text.Text))]))]),
                AdapterUsage usage => new JsonObject([Property("usage", ProjectUsage(usage.Usage))]),
                AdapterFinal final => new JsonObject([Property("final", new JsonObject([
                    Property("finish_reason", NullableString(final.FinishReason)),
                    Property("usage", final.Usage is null ? JsonNull.Instance : ProjectUsage(final.Usage)),
                ]))]),
                _ => throw new ObservationUnavailableException("transport adapter emitted an unknown event"),
            });
        }

        if (run.TerminalException is not null)
        {
            return new JsonObject([Property("error", ProjectError(run.TerminalException))]);
        }

        return new JsonObject([Property("events", new JsonArray(events))]);
    }

    private static JsonObject ProjectUsage(Usage usage) => new([
        Property("input_tokens", NullableInteger(usage.InputTokens)),
        Property("output_tokens", NullableInteger(usage.OutputTokens)),
        Property("total_tokens", NullableInteger(usage.TotalTokens)),
        Property("cache_read_tokens", NullableInteger(usage.CacheReadTokens)),
        Property("cache_write_tokens", NullableInteger(usage.CacheWriteTokens)),
        Property("reasoning_tokens", NullableInteger(usage.ReasoningTokens)),
    ]);

    private static JsonObject ProjectError(ProviderException error) => new([
        Property("category", String(error.Category)),
        Property("retryable", new JsonBoolean(error.Retryable)),
        Property("retry_after_s", error.RetryAfterS is null ? JsonNull.Instance : Number(error.RetryAfterS.Value)),
        Property("http_status", error.HttpStatus is null ? JsonNull.Instance : Integer(error.HttpStatus.Value)),
        Property("phase", NullableString(error.Phase)),
    ]);

    private static JsonProperty Property(string name, JsonValue value) => new(name, value);
    private static JsonString String(string value) => new(value);
    private static JsonInteger Integer(int value) => new(new BigInteger(value));
    private static JsonValue NullableInteger(long? value) => value is null ? JsonNull.Instance : new JsonInteger(new BigInteger(value.Value));
    private static JsonNumber Number(double value) => new(value);
    private static JsonValue NullableString(string? value) => value is null ? JsonNull.Instance : String(value);
}
