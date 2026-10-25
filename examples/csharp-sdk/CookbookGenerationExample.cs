using System.Text.Json.Serialization;
using AnyInfer.Config;

namespace AnyInfer.Examples;

/// <summary>
/// A release-notes summarizer service: configuration-driven routing with fallback, schema-validated
/// output deserialized into an application record, and a per-document attempt and usage report.
/// </summary>
public static class CookbookGenerationExample
{
    /// <summary>
    /// The service's version 1 configuration. A deployment keeps this text in <c>anyinfer.json</c>
    /// and reads it with <see cref="AnyInferConfig.Load"/>; credentials stay <c>env://</c> references.
    /// </summary>
    public const string Configuration = """
        {
          "format_version": 1,
          "providers": [
            {"id": "cerebras", "api_key": "env://CEREBRAS_API_KEY", "timeout_s": 30},
            {"id": "local", "adapter": "openai-compat", "base_url": "http://127.0.0.1:8000/v1", "timeout_s": 60}
          ],
          "default_route": ["cerebras:gpt-oss-120b", "local:qwen3-8b"],
          "repair": {"max_attempts": 1}
        }
        """;

    private static readonly SchemaSpec SummarySchema = SchemaSpec.FromJson("""
        {
          "$schema": "https://json-schema.org/draft/2020-12/schema",
          "title": "release_summary",
          "type": "object",
          "required": ["headline", "risk", "topics"],
          "additionalProperties": false,
          "properties": {
            "headline": {"type": "string", "minLength": 1},
            "risk": {"enum": ["low", "medium", "high"]},
            "topics": {"type": "array", "items": {"type": "string"}, "minItems": 1}
          }
        }
        """);

    /// <summary>Summarizes each release note in order with one client and writes an operator report.</summary>
    /// <param name="config">Loaded configuration that supplies the providers, default route and repair budget.</param>
    /// <param name="releaseNotes">Release notes to summarize, keyed by the application's own identifier.</param>
    /// <param name="output">Where the operator report is written, such as <see cref="Console.Out"/>.</param>
    /// <param name="cancellationToken">Cancels the remaining work.</param>
    /// <returns>One outcome per release note, in input order.</returns>
    public static async Task<IReadOnlyList<CookbookSummaryOutcome>> RunAsync(
        AnyInferConfig config,
        IReadOnlyList<CookbookReleaseNote> releaseNotes,
        TextWriter output,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(config);
        ArgumentNullException.ThrowIfNull(releaseNotes);
        ArgumentNullException.ThrowIfNull(output);

        await using var client = AsyncClient.FromConfig(config);
        var outcomes = new List<CookbookSummaryOutcome>();
        foreach (var note in releaseNotes)
        {
            try
            {
                var generation = await client.GenerateAsync(
                    "Summarize these release notes for the on-call operator.\n\n" + note.Text,
                    schema: SummarySchema,
                    sampling: new Sampling(temperature: 0, maxOutputTokens: 400),
                    metadata: new Dictionary<string, string> { ["release"] = note.Id },
                    cancellationToken: cancellationToken).ConfigureAwait(false);
                var summary = generation.DeserializeStructured<ReleaseSummary>()
                    ?? throw new InvalidOperationException("The validated summary was JSON null.");
                var outcome = new CookbookSummaryOutcome(note.Id, summary, generation.Target?.ToString(), generation.StructuredMechanism, generation.RepairAttempts, generation.Usage, Trail(generation.Attempts), null);
                outcomes.Add(outcome);
                await output.WriteLineAsync($"{note.Id}: [{summary.Risk}] {summary.Headline} (via {outcome.ServedBy}, {outcome.Mechanism}, {outcome.Repairs} repair(s), {generation.Usage?.TotalTokens?.ToString() ?? "unknown"} tokens)").ConfigureAwait(false);
            }
            catch (AllTargetsFailedException failure)
            {
                outcomes.Add(new CookbookSummaryOutcome(note.Id, null, null, null, 0, null, Trail(failure.Attempts), failure.Category));
                await output.WriteLineAsync($"{note.Id}: not summarized ({failure.Category})").ConfigureAwait(false);
            }
            catch (SchemaViolationException violation)
            {
                outcomes.Add(new CookbookSummaryOutcome(note.Id, null, null, null, 0, null, [], violation.Category));
                await output.WriteLineAsync($"{note.Id}: not summarized ({violation.Category}: {violation.Issues.Count} issue(s))").ConfigureAwait(false);
            }

            foreach (var attempt in outcomes[^1].Attempts)
            {
                await output.WriteLineAsync($"  {attempt}").ConfigureAwait(false);
            }
        }

        return outcomes;
    }

    private static IReadOnlyList<string> Trail(IEnumerable<AttemptRecord> attempts) =>
        attempts.Select(static attempt => attempt.Error is null
            ? $"{attempt.Target}: {attempt.Outcome}"
            : $"{attempt.Target}: {attempt.Outcome} ({attempt.Error.GetType().Name}, HTTP {attempt.Error.HttpStatus?.ToString() ?? "-"})").ToArray();

    /// <summary>The application record the validated structured output is deserialized into.</summary>
    /// <param name="Headline">One-line summary for the operator.</param>
    /// <param name="Risk">Deployment risk: <c>low</c>, <c>medium</c> or <c>high</c>.</param>
    /// <param name="Topics">Areas the release touches.</param>
    public sealed record ReleaseSummary(
        [property: JsonPropertyName("headline")] string Headline,
        [property: JsonPropertyName("risk")] string Risk,
        [property: JsonPropertyName("topics")] IReadOnlyList<string> Topics);
}

/// <summary>One release note the application wants summarized.</summary>
/// <param name="Id">The application's identifier for the release.</param>
/// <param name="Text">The release-note text.</param>
public sealed record CookbookReleaseNote(string Id, string Text);

/// <summary>The summarizer's result for one release note.</summary>
/// <param name="ReleaseId">The application's identifier for the release.</param>
/// <param name="Summary">The validated summary, or <see langword="null"/> when the note could not be summarized.</param>
/// <param name="ServedBy">The <c>provider:model</c> target that produced the summary.</param>
/// <param name="Mechanism">How the schema was enforced on the winning target.</param>
/// <param name="Repairs">Schema-repair round trips spent on the winning target.</param>
/// <param name="Usage">Reported usage of the winning call, or <see langword="null"/> when unknown.</param>
/// <param name="Attempts">The routing trail, one line per attempt.</param>
/// <param name="FailureCategory">The failure category when the note was not summarized.</param>
public sealed record CookbookSummaryOutcome(
    string ReleaseId,
    CookbookGenerationExample.ReleaseSummary? Summary,
    string? ServedBy,
    string? Mechanism,
    int Repairs,
    Usage? Usage,
    IReadOnlyList<string> Attempts,
    string? FailureCategory);
