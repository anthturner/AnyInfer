using AnyInfer.Json;
using AnyInfer.Manifest;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Literal Python-format render controls for format-one manifests.</summary>
public sealed class ManifestRenderingTests
{
    [Fact]
    public void Default_render_has_exact_header_required_sections_and_no_trailing_newline()
    {
        const string expected = """
        run (unknown) - incomplete (stream not drained)
          anyinfer ?, manifest format 1
          route
            requested   (none)
            resolved    (none)
          usage
            tokens      ? in / ? out
            cost        unknown (no trusted pricing)
        """;

        var rendered = ManifestUtilities.Render(new RunManifest());
        Assert.Equal(expected, rendered);
        Assert.False(rendered.EndsWith("\n", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData(null, "unknown (no trusted pricing)")]
    [InlineData("", "unknown (no trusted pricing)")]
    [InlineData("0", "$0")]
    [InlineData("-0", "$-0")]
    [InlineData("NaN", "$NaN")]
    [InlineData("Infinity", "$Infinity")]
    public void Monetary_strings_are_verbatim_except_for_null_or_empty_unknown(string? value, string expected)
    {
        var rendered = ManifestUtilities.Render(new RunManifest(usage: new UsageFacet(costUsd: value)));
        Assert.Contains("    cost        " + expected, rendered, StringComparison.Ordinal);
    }

    [Fact]
    public void Full_optional_sections_follow_python_order_and_scalar_padding_counts_astral_names_once()
    {
        var manifest = new RunManifest(
            anyinferVersion: "v", requestId: "r", complete: true,
            route: new RouteFacet(["alpha:model"], "alpha:model", [new RouteStep("alpha:model", "selected", "ok")]),
            attempts: [new AttemptFacet("alpha:model", 1, "ok", new ErrorInfo("E", null, null, false, null, "bad"), firstTokenMs: 2, totalMs: 3, queuedMs: 1, retryDelayS: 0.5)],
            structured: new SchemaFacet(true, "json_schema", "json_schema", [new MechanismRung("json_schema", true, "native")], 1, [new RepairRecord(1, errors: ["invalid"])]),
            capability: new CapabilityFacet("alpha:model", [new SourcedFact("😀", new JsonInteger(1), "catalog")]),
            cache: new CacheFacet("auto", "prefix", 1, 2, 3),
            context: new ContextFacet([new ReductionRecord("trim", "summary", 4, 2, 2)]),
            dropped: [new DroppedParameter("alpha:model", "top_p", "unsupported")],
            usage: new UsageFacet(1, 2, estimatedFields: [new("z", "heuristic")]),
            timing: new TimingFacet(2, 3, phases: [new("😀", 4)]), notes: ["note"], payloads: new PayloadFacet());

        const string expected = """
        run r - complete
          anyinfer v, manifest format 1
          route
            requested   alpha:model
            resolved    alpha:model
            * alpha:model: selected - ok
          attempts
            #1 alpha:model ok 3ms ttft 2ms queued 1ms
              error: bad
              retry after 0.50s
          structured output
            chosen      json_schema (used: json_schema)
            + json_schema - native
            repairs     1
              #1: invalid
          capabilities (alpha:model)
            😀                   1 [catalog]
          cache
            policy      auto
            mechanism   prefix
            marks       1
            reported    3 read
          reduced trim -> summary: 2/4 kept, 2 omitted
          dropped top_p: unsupported
          usage
            tokens      1 in / 2 out
            cost        unknown (no trusted pricing)
            estimated   z: heuristic
          timing
            total       3 ms
            first token 2 ms
            😀           4 ms
          note: note
          payloads captured (redacted)
        """;

        Assert.Equal(expected, ManifestUtilities.Render(manifest));
    }

    [Fact]
    public void Narrow_width_wraps_hyphenated_and_unbroken_notes_with_remaining_capacity()
    {
        var rendered = ManifestUtilities.Render(new RunManifest(notes: ["very-long-unbroken-token-abcdefghijklmnopqrstuvwxyz"]), 24);
        const string expectedNote = """
          note: very-long-
            unbroken-token-abcde
            fghijklmnopqrstuvwxy
            z
        """;
        Assert.Contains(expectedNote, rendered, StringComparison.Ordinal);

        var widthTwelve = ManifestUtilities.Render(new RunManifest(notes: ["a-b-c-d-e-f-g-h-i"]), 12);
        Assert.Contains("  note: a-b-\n    c-d-e-f-\n    g-h-i", widthTwelve, StringComparison.Ordinal);
    }

    [Fact]
    public void Narrow_width_estimated_field_wrapping_never_retains_trailing_spaces()
    {
        var rendered = ManifestUtilities.Render(new RunManifest(usage: new UsageFacet(estimatedFields: [new("input_tokens", "estimated")])), 12);
        const string expectedTail = """
            estimate
              d   in
              put_to
              kens:
              estima
              ted
        """;
        Assert.Contains(expectedTail, rendered, StringComparison.Ordinal);
        Assert.All(rendered.Split('\n'), line => Assert.Equal(line.TrimEnd(), line));
    }
}
