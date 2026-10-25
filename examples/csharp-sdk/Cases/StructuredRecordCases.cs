using System.Text.Json;
using System.Text.Json.Serialization;
using AnyInfer.Events;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes the structured-output recipes published in the structured-output guide.</summary>
internal static class StructuredRecordCases
{
    private const string Valid = """{"sentiment":"positive","score":4,"themes":["battery","screen"]}""";
    private const string OutOfRange = """{"sentiment":"positive","score":9,"themes":["battery"]}""";
    private const string Review = "Great battery, sharp screen.";

    [ExampleCase("structured-record.valid-first-time")]
    internal static async Task ValidFirstTime()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text(Valid), GuideScripts.Text(Valid));
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        var analysis = await StructuredRecordExample.AnalyzeAsync(client, ExampleSupport.Target, Review);
        ExampleSupport.Require(analysis is { Sentiment: "positive", Score: 4 }
            && analysis.Themes.SequenceEqual(["battery", "screen"])
            && handler.RequestCount == 1,
            "A valid first answer was not deserialized into the application record.");
        using (var first = handler.Request(0))
        {
            var messages = first.RootElement.GetProperty("messages").EnumerateArray().ToArray();
            ExampleSupport.Require(!first.RootElement.TryGetProperty("response_format", out _)
                && messages[0].GetProperty("role").GetString() == "system"
                && messages[0].GetProperty("content").GetString()!.StartsWith("Respond with ONLY a JSON value matching this JSON Schema.", StringComparison.Ordinal)
                && messages[0].GetProperty("content").GetString()!.Contains("\"maximum\": 5", StringComparison.Ordinal),
                "The generic OpenAI-compatible target did not receive prompt-based schema instructions.");
        }

        var generation = await client.GenerateAsync("Analyze this review:\n" + Review, target: ExampleSupport.Target, schema: StructuredRecordExample.Review);
        ExampleSupport.Require(StructuredRecordExample.Explain(generation) == "prompt after 0 repair round trip(s)"
            && generation.Structured is not null,
            "The structured mechanism or repair count was not reported.");
    }

    [ExampleCase("structured-record.repaired")]
    internal static async Task Repaired()
    {
        var handler = new GuideScripts.ChatHandler(
            GuideScripts.Text(OutOfRange), GuideScripts.Text(Valid),
            GuideScripts.Text(OutOfRange), GuideScripts.Text(Valid));
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        var analysis = await StructuredRecordExample.AnalyzeAsync(client, ExampleSupport.Target, Review);
        ExampleSupport.Require(analysis.Score == 4 && handler.RequestCount == 2,
            "One repair round trip did not recover a valid analysis.");
        using (var repair = handler.Request(1))
        {
            var messages = repair.RootElement.GetProperty("messages").EnumerateArray().ToArray();
            ExampleSupport.Require(messages.Any(static message => message.GetProperty("role").GetString() == "assistant"
                    && message.GetProperty("content").GetString() == OutOfRange),
                "The repair request did not return the invalid answer to the model.");
        }

        var generation = await client.GenerateAsync(
            "Analyze this review:\n" + Review,
            target: ExampleSupport.Target,
            schema: StructuredRecordExample.Review,
            repair: new Repair(1));
        ExampleSupport.Require(StructuredRecordExample.Explain(generation) == "prompt after 1 repair round trip(s)",
            "The repair count was not reported.");
    }

    [ExampleCase("structured-record.repair-exhausted")]
    internal static async Task RepairExhausted()
    {
        var primary = new GuideScripts.ChatHandler(
            GuideScripts.Text(OutOfRange), GuideScripts.Text(OutOfRange),
            GuideScripts.Text(OutOfRange), GuideScripts.Text(OutOfRange));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text(Valid));
        await using var client = new AsyncClient([GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")]);
        var log = new StringWriter();
        var analysis = await StructuredRecordExample.TryAnalyzeAsync(client, "primary:demo", Review, log);
        ExampleSupport.Require(analysis is null
            && log.ToString() == $"The response did not satisfy the requested schema. Failed rules: maximum{Environment.NewLine}"
            && primary.RequestCount == 2,
            $"An exhausted repair budget was logged as '{log}'.");

        var failure = await GuideScripts.ExpectThrowsAsync<SchemaViolationException>(
            () => client.GenerateAsync(
                "Analyze this review:\n" + Review,
                route: new Route(["primary:demo", "backup:demo"]),
                schema: StructuredRecordExample.Review,
                repair: new Repair(1)),
            "An exhausted repair budget did not raise SchemaViolationException.");
        ExampleSupport.Require(failure.Issues.Single().Rule == "maximum"
            && primary.RequestCount == 4
            && backup.RequestCount == 0,
            "A schema violation fell back to another target.");
    }

    [ExampleCase("structured-record.no-structured-value")]
    internal static async Task NoStructuredValue()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        var generation = await client.GenerateAsync("Say hello.", target: ExampleSupport.Target);
        GuideScripts.ExpectThrows<InvalidOperationException>(
            () => generation.DeserializeStructured<StructuredRecordExample.ReviewAnalysis>(),
            "A generation without a schema was deserialized.");
    }

    [ExampleCase("structured-record.record-shape-mismatch")]
    internal static async Task RecordShapeMismatch()
    {
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text("""{"answer":"ok"}"""));
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        var generation = await client.GenerateAsync(
            "Return an answer object.",
            target: ExampleSupport.Target,
            schema: SchemaSpec.FromJson("""{"type":"object","required":["answer"],"properties":{"answer":{"type":"string"}}}"""));
        var mismatch = generation.DeserializeStructured<StructuredRecordExample.ReviewAnalysis>();
        ExampleSupport.Require(mismatch is { Sentiment: null, Score: 0, Themes: null } && handler.RequestCount == 1,
            "System.Text.Json did not apply its ordinary missing-member defaults to a record the schema does not describe.");
        GuideScripts.ExpectThrows<JsonException>(
            () => generation.DeserializeStructured<StrictReview>(),
            "A [JsonRequired] record member missing from the validated value was accepted.");
    }

    [ExampleCase("structured-record.missing-member-and-repair-payload")]
    internal static async Task MissingMemberAndRepairPayload()
    {
        const string missingThemes = """{"sentiment":"neutral","score":3}""";
        var handler = new GuideScripts.ChatHandler(GuideScripts.Text(missingThemes), GuideScripts.Text(missingThemes));
        var observer = new RepairObserver();
        await using var client = new AsyncClient([GuideScripts.Instance(handler)]);
        client.Subscribe(observer, payloads: true);
        var log = new StringWriter();
        var analysis = await StructuredRecordExample.TryAnalyzeAsync(client, ExampleSupport.Target, Review, log);
        ExampleSupport.Require(analysis is null
            && log.ToString().EndsWith($"Failed rules: required{Environment.NewLine}", StringComparison.Ordinal)
            && observer.RawTexts.SequenceEqual([missingThemes]),
            $"A missing member was logged as '{log}' with repair payloads [{string.Join(", ", observer.RawTexts)}].");
    }

    /// <summary>A record whose members System.Text.Json must find in the JSON.</summary>
    private sealed record StrictReview(
        [property: JsonPropertyName("sentiment"), JsonRequired] string Sentiment);

    /// <summary>Collects the answer text each repair round trip was asked to correct.</summary>
    private sealed class RepairObserver : IObserver
    {
        public List<string?> RawTexts { get; } = [];

        public void OnEvent(TelemetryEvent telemetryEvent)
        {
            if (telemetryEvent is RepairAttempted repair)
            {
                RawTexts.Add(repair.RawText);
            }
        }
    }
}
