using System.Collections.Generic;
using System.Numerics;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

public sealed class PublicModelTests
{
    [Fact]
    public void Json_object_preserves_first_position_and_last_value_for_duplicate_name()
    {
        var value = new JsonObject([
            new JsonProperty("first", new JsonInteger(1)),
            new JsonProperty("later", new JsonInteger(2)),
            new JsonProperty("first", new JsonInteger(3)),
        ]);

        Assert.Collection(value.Properties,
            property => Assert.Equal(new JsonInteger(3), property.Value),
            property => Assert.Equal(new JsonInteger(2), property.Value));
        Assert.True(value.TryGetValue("first", out var first));
        Assert.Equal(new JsonInteger(3), first);
    }

    [Fact]
    public void Json_integer_keeps_inclusive_int64_endpoints_without_narrowing()
    {
        Assert.Equal(new BigInteger(long.MinValue), new JsonInteger(new BigInteger(long.MinValue)).Value);
        Assert.Equal(new BigInteger(long.MaxValue) + BigInteger.One, new JsonInteger(new BigInteger(long.MaxValue) + BigInteger.One).Value);
    }

    [Fact]
    public void Json_number_retains_negative_zero_and_lexeme()
    {
        var value = new JsonNumber(-0.0, "-0.0");

        Assert.True(value.IsNegativeZero);
        Assert.Equal("-0.0", value.SourceLexeme);
    }

    [Fact]
    public void Containers_defensively_copy_callers()
    {
        var properties = new List<JsonProperty> { new("a", JsonNull.Instance) };
        var parts = new List<ContentPart> { new Text("hello") };
        var objectValue = new JsonObject(properties);
        var message = new Message("user", parts);
        properties.Add(new JsonProperty("b", JsonNull.Instance));
        parts.Clear();

        Assert.Single(objectValue.Properties);
        Assert.Single(message.Content);
    }

    [Fact]
    public void Public_input_collections_snapshot_caller_owned_values()
    {
        var stop = new List<string> { "stop-one", "stop-two" };
        var targets = new List<string> { "fixture:alpha", "fixture:beta" };
        var messages = new List<Message> { new("user", [new Text("first")]) };
        var wireMessages = new List<Message> { new("system", [new Text("wire")]) };
        var sampling = new Sampling(stop: stop);
        var route = new Route(targets);
        var request = new GenerationRequest(messages, route, sampling: sampling);
        var wire = new WireRequest("alpha", wireMessages, sampling);

        stop.Clear();
        targets.Clear();
        messages.Clear();
        wireMessages.Clear();

        Assert.Equal(new[] { "stop-one", "stop-two" }, sampling.Stop);
        Assert.Equal(new[] { "fixture:alpha", "fixture:beta" }, route.Targets);
        Assert.Equal("first", Assert.IsType<Text>(Assert.Single(request.Messages[0].Content)).Value);
        Assert.Equal("wire", Assert.IsType<Text>(Assert.Single(wire.Messages[0].Content)).Value);
    }

    [Fact]
    public void Raw_excluded_forms_and_route_defaults_are_retained()
    {
        var request = new GenerationRequest(
            [new Message("tool", [new UnsupportedContentPart("image", new JsonObject([new JsonProperty("url", new JsonString("https://example.invalid/image"))]))])],
            new Route(["fixture: model:with:colon"]),
            sampling: new Sampling(maxOutputTokens: 12, stop: []),
            schema: new JsonObject([new JsonProperty("anyOf", new JsonArray([]))]),
            timeoutS: null,
            maxResponseBytes: null);

        Assert.IsType<UnsupportedContentPart>(Assert.Single(request.Messages[0].Content));
        Assert.Equal("tool", request.Messages[0].Role);
        Assert.Equal("fixture: model:with:colon", Assert.Single(request.Route.Targets));
        Assert.Equal(2, request.Route.Retry.MaxAttempts);
        Assert.Equal(0.5, request.Route.Retry.BackoffBaseS);
        Assert.Equal(30, request.Route.Retry.BackoffMaxS);
        Assert.True(request.Route.HealthGate);
        Assert.Equal(30, request.Route.HealthTtlS);
        Assert.Equal(12, request.Sampling!.MaxOutputTokens);
        Assert.NotNull(request.Sampling.Stop);
        Assert.Empty(request.Sampling.Stop!);
        Assert.Null(request.TimeoutS);
        Assert.Null(request.MaxResponseBytes);
        Assert.Null(request.Repair);
    }

    [Fact]
    public void Sampling_retains_raw_invalid_construction_values_without_coercion()
    {
        var sampling = new Sampling(seed: -1, presencePenalty: double.PositiveInfinity, frequencyPenalty: double.NaN);

        Assert.Equal(-1, sampling.Seed);
        Assert.True(double.IsPositiveInfinity(sampling.PresencePenalty!.Value));
        Assert.True(double.IsNaN(sampling.FrequencyPenalty!.Value));
    }

    [Fact]
    public void Result_retains_usage_timing_attempts_and_warnings()
    {
        var target = new ResolvedTarget("fixture", "model");
        var providerError = new ProviderException("offline", "transport", true, "stream", 0.5, 503, "fixture", "bounded", "retry");
        var attemptItems = new List<AttemptRecord> { new(target, "failed", providerError) };
        var warnings = new List<string> { "adapter warning" };
        var result = new Generation("done", target: target, finishReason: "stop",
            usage: new Usage(1, 2, 3, 4, 5, 6), timing: new Timing(startedAt: 7, firstTokenMs: 8, totalMs: 9),
            structuredMechanism: "prompt", repairAttempts: 1, attempts: attemptItems, warnings: warnings);
        attemptItems.Clear();
        warnings.Clear();

        Assert.Equal("fixture", result.Target!.ProviderId);
        Assert.Equal("model", result.Target.Model);
        Assert.Equal(6, result.Usage!.ReasoningTokens);
        Assert.Equal(7, result.Timing!.StartedAt);
        Assert.Equal(8, result.Timing.FirstTokenMs);
        Assert.Equal("prompt", result.StructuredMechanism);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Single(result.Attempts);
        Assert.Single(result.Warnings);
        Assert.Equal("transport", result.Attempts[0].Error!.Category);
        Assert.IsType<AttemptFailed>(new AttemptFailed(result.Attempts[0]));
    }

    [Fact]
    public void Typed_errors_copy_issues_and_attempt_trails()
    {
        var issueSegments = new List<object> { "properties", "age", 0 };
        var issue = new Issue("type", issueSegments, ["properties", "age", "type"], new JsonObject([]));
        var issues = new List<Issue> { issue };
        var schemaError = new SchemaViolationException("bad age", issues, provider: "fixture");
        issues.Clear();
        issueSegments.Clear();
        var attempt = new AttemptRecord(new ResolvedTarget("fixture", "model"), "failed", schemaError);
        var trail = new List<AttemptRecord> { attempt };
        var allFailed = new AllTargetsFailedException("all failed", trail);
        trail.Clear();

        Assert.Equal("schema_violation", schemaError.Category);
        Assert.False(schemaError.Retryable);
        Assert.Equal("validate", schemaError.Phase);
        Assert.Single(schemaError.Issues);
        Assert.Equal(new object[] { "properties", "age", 0 }, schemaError.Issues[0].InstancePath);
        Assert.Equal("all_targets_failed", allFailed.Category);
        Assert.False(allFailed.Retryable);
        Assert.Equal("generate", allFailed.Phase);
        Assert.Single(allFailed.Attempts);
    }

    [Fact]
    public void Base_and_provider_errors_retain_nullable_construction_or_cancellation_phase()
    {
        var invalidRequest = new AnyInferException("invalid", "invalid_request", false, null);
        var cancelled = new AnyInferException("cancelled", "cancelled", false, null);
        var provider = new ProviderException("unavailable", "provider_unavailable", true, null, provider: "fixture");
        var schema = new SchemaViolationException("schema", []);
        var allFailed = new AllTargetsFailedException("all", []);

        Assert.Null(invalidRequest.Phase);
        Assert.Equal("invalid_request", invalidRequest.Category);
        Assert.False(invalidRequest.Retryable);
        Assert.Null(cancelled.Phase);
        Assert.Equal("cancelled", cancelled.Category);
        Assert.False(cancelled.Retryable);
        Assert.Null(provider.Phase);
        Assert.True(provider.Retryable);
        Assert.Equal("validate", schema.Phase);
        Assert.Equal("generate", allFailed.Phase);
    }

    [Fact]
    public void Provider_contract_is_lazy_async_enumerable_with_optional_token()
    {
        var method = typeof(IGeneratesText).GetMethod(nameof(IGeneratesText.GenerateAsync));

        Assert.NotNull(method);
        Assert.True(typeof(IGeneratesText).IsAssignableFrom(typeof(IProviderAdapter)));
        Assert.True(typeof(IAsyncDisposable).IsAssignableFrom(typeof(IProviderAdapter)));
        Assert.Equal(typeof(IAsyncEnumerable<AdapterEvent>), method.ReturnType);
        var parameter = Assert.Single(method.GetParameters().Skip(1));
        Assert.Equal(typeof(CancellationToken), parameter.ParameterType);
        Assert.True(parameter.HasDefaultValue);
    }
}
