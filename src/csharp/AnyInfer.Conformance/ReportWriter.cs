using System.Numerics;
using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Conformance;

/// <summary>Creates unqualified development observations from released core fixture inputs.</summary>
internal static class ReportWriter
{
    private const int MaximumDiagnosticLength = 512;
    private const string DevelopmentFileName = "csharp-development.json";

    internal static async Task<JsonObject> RunDevelopmentAsync(
        ReleaseAssets assets,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(assets);

        var fixtures = FixtureReader.ReadFixtures(assets)
            .ToDictionary(static document => document.Case.Id, StringComparer.Ordinal);
        var cases = new List<JsonValue>();
        var unavailable = new List<JsonValue>();
        var counts = new DevelopmentCounts();

        foreach (var inventoryCase in assets.Cases)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (inventoryCase.Kind != FixtureKind.Fixture ||
                !fixtures.TryGetValue(inventoryCase.Id, out var fixture) ||
                fixture.Input is not CoreFixtureInput coreInput)
            {
                unavailable.Add(new JsonString(inventoryCase.Id));
                counts.Unavailable++;
                continue;
            }

            cases.Add(await RunCoreCaseAsync(fixture, coreInput, counts, cancellationToken).ConfigureAwait(false));
        }

        return new JsonObject([
            new JsonProperty("development_version", new JsonInteger(BigInteger.Zero)),
            new JsonProperty("status", new JsonString("DEVELOPMENT/UNRELEASED")),
            new JsonProperty("release_input", new JsonObject([
                new JsonProperty("id", new JsonString(assets.ReleaseId)),
                new JsonProperty("sha256", new JsonString(assets.ReleaseSha256)),
            ])),
            new JsonProperty("available_subset", new JsonString("core-fixtures")),
            new JsonProperty("cases", new JsonArray(cases)),
            new JsonProperty("unavailable", new JsonArray(unavailable)),
            new JsonProperty("counts", new JsonObject([
                new JsonProperty("pass", new JsonInteger(counts.Pass)),
                new JsonProperty("fail", new JsonInteger(counts.Fail)),
                new JsonProperty("error", new JsonInteger(counts.Error)),
                new JsonProperty("unavailable", new JsonInteger(counts.Unavailable)),
            ])),
        ]);
    }

    internal static async Task<string> WriteDevelopmentAsync(
        ReleaseAssets assets,
        string? outputPath,
        CancellationToken cancellationToken = default)
    {
        var destination = ResolveDevelopmentOutputPath(outputPath);
        var document = await RunDevelopmentAsync(assets, cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        var encoded = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)
            .GetBytes(JsonWriter.Write(document) + "\n");
        File.WriteAllBytes(destination, encoded);
        return destination;
    }

    internal static bool HasFailureOrError(JsonObject document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (!document.TryGetValue("counts", out var countsValue) || countsValue is not JsonObject counts)
        {
            throw new InvalidOperationException("Development document has no counts.");
        }

        return Count(counts, "fail") != 0 || Count(counts, "error") != 0;
    }

    private static async Task<JsonObject> RunCoreCaseAsync(
        FixtureDocument fixture,
        CoreFixtureInput input,
        DevelopmentCounts counts,
        CancellationToken cancellationToken)
    {
        try
        {
            var run = await NativeRunner.RunAsync(fixture.Case.Id, input, cancellationToken).ConfigureAwait(false);
            var comparison = Comparison.Compare(fixture, run);
            switch (comparison.Verdict)
            {
                case "pass":
                    counts.Pass++;
                    break;
                case "fail":
                    counts.Fail++;
                    break;
                case "error":
                    counts.Error++;
                    break;
                default:
                    throw new InvalidOperationException("Development comparison returned an unsupported verdict.");
            }

            return CaseDocument(fixture.Case.Id, comparison.Verdict, comparison.Detail, comparison.Observation);
        }
        catch (ObservationUnavailableException exception)
        {
            return HarnessErrorCase(fixture.Case.Id, exception, counts);
        }
        catch (InvalidOperationException exception)
        {
            return HarnessErrorCase(fixture.Case.Id, exception, counts);
        }
        catch (ArgumentException exception)
        {
            return HarnessErrorCase(fixture.Case.Id, exception, counts);
        }
        catch (FormatException exception)
        {
            return HarnessErrorCase(fixture.Case.Id, exception, counts);
        }
        catch (OverflowException exception)
        {
            return HarnessErrorCase(fixture.Case.Id, exception, counts);
        }
    }

    private static JsonObject HarnessErrorCase(string caseId, Exception exception, DevelopmentCounts counts)
    {
        counts.Error++;
        var type = exception.GetType().Name;
        var detail = BoundedDiagnostic(exception.Message);
        return CaseDocument(
            caseId,
            "error",
            $"{type}: {detail}",
            new JsonObject([
                new JsonProperty("diagnostic_type", new JsonString(type)),
                new JsonProperty("diagnostic", new JsonString(detail)),
            ]));
    }

    private static JsonObject CaseDocument(string caseId, string verdict, string? detail, JsonObject observation) =>
        new([
            new JsonProperty("id", new JsonString(caseId)),
            new JsonProperty("verdict", new JsonString(verdict)),
            new JsonProperty("detail", detail is null ? JsonNull.Instance : new JsonString(BoundedDiagnostic(detail))),
            new JsonProperty("observation", observation),
        ]);

    private static string ResolveDevelopmentOutputPath(string? outputPath)
    {
        var outputRoot = ResolveDevelopmentOutputRoot();
        EnsureExistingAncestorsAreNotReparsePoints(outputRoot);
        if (!Directory.Exists(outputRoot))
        {
            Directory.CreateDirectory(outputRoot);
        }

        RejectReparsePoint(outputRoot);
        var candidate = outputPath is null
            ? Path.Combine(outputRoot, DevelopmentFileName)
            : Path.IsPathFullyQualified(outputPath)
                ? outputPath
                : Path.Combine(outputRoot, outputPath);
        var fullPath = Path.GetFullPath(candidate);
        var relative = Path.GetRelativePath(outputRoot, fullPath);
        if (Path.IsPathFullyQualified(relative) ||
            relative is "." or ".." ||
            relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal))
        {
            throw new ArgumentException("Development output must be under .tmp-tests.", nameof(outputPath));
        }

        var parent = Path.GetDirectoryName(fullPath)
            ?? throw new ArgumentException("Development output has no parent directory.", nameof(outputPath));
        if (!Directory.Exists(parent))
        {
            throw new ArgumentException("Development output parent directory does not exist.", nameof(outputPath));
        }

        EnsureExistingAncestorsAreNotReparsePoints(fullPath);
        return fullPath;
    }

    private static string ResolveDevelopmentOutputRoot()
    {
        var executableDirectory = AppContext.BaseDirectory;
        var root = Path.GetFullPath(Path.Combine(
            executableDirectory,
            "..", "..", "..", "..", "..", "..", ".tmp-tests"));
        return root;
    }

    private static void EnsureExistingAncestorsAreNotReparsePoints(string fullPath)
    {
        var root = Path.GetPathRoot(fullPath) ?? throw new ArgumentException("Path has no root.", nameof(fullPath));
        var current = root;
        var relative = fullPath[root.Length..];
        foreach (var segment in relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
        {
            if (string.IsNullOrEmpty(segment))
            {
                continue;
            }

            current = Path.Combine(current, segment);
            if (File.Exists(current) || Directory.Exists(current))
            {
                RejectReparsePoint(current);
            }
        }
    }

    private static void RejectReparsePoint(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw new ArgumentException("Development output path contains a reparse point.", nameof(path));
        }
    }

    private static long Count(JsonObject counts, string name) =>
        counts.TryGetValue(name, out var value) && value is JsonInteger integer &&
        integer.Value >= BigInteger.Zero && integer.Value <= long.MaxValue
            ? (long)integer.Value
            : throw new InvalidOperationException("Development count is invalid.");

    private static string BoundedDiagnostic(string value)
    {
        ArgumentNullException.ThrowIfNull(value);
        var sanitized = new StringBuilder(Math.Min(value.Length, MaximumDiagnosticLength));
        foreach (var character in value)
        {
            if (sanitized.Length == MaximumDiagnosticLength)
            {
                break;
            }

            sanitized.Append(char.IsControl(character) || character is '\u2028' or '\u2029' ? ' ' : character);
        }

        return sanitized.ToString();
    }

    private sealed class DevelopmentCounts
    {
        internal long Pass { get; set; }
        internal long Fail { get; set; }
        internal long Error { get; set; }
        internal long Unavailable { get; set; }
    }
}
