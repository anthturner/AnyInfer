using System.Numerics;
using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Conformance;

internal delegate FinalReportProvenanceFacts FinalReportFactsObserver(string repositoryRoot, string expectedRevision);

/// <summary>Builds and publishes the native proof report after all production guards succeed.</summary>
internal static class FinalReportWriter
{
    internal static async Task<string> WriteAsync(
        ReleaseAssets assets,
        FinalReportProvenanceFacts provenance,
        CancellationToken cancellationToken,
        Func<CancellationToken, Task>? beforeFinalGuards = null)
    {
        ArgumentNullException.ThrowIfNull(assets);
        ArgumentNullException.ThrowIfNull(provenance);
        FinalReportProvenance.ValidateFacts(provenance);
        VerifyReleaseBinding(assets);
        cancellationToken.ThrowIfCancellationRequested();

        var development = await ReportWriter.RunDevelopmentAsync(assets, cancellationToken).ConfigureAwait(false);
        var report = BuildReport(assets, provenance, development);
        ValidateReport(report, assets);
        var bytes = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)
            .GetBytes(JsonWriter.Write(report) + "\n");

        var destination = Path.Combine(
            provenance.RepositoryRoot,
            "specification",
            "reports",
            "csharp-" + provenance.ExpectedRevision[..7] + ".json");
        return await PublishPreparedAsync(
            assets,
            provenance,
            destination,
            bytes,
            cancellationToken,
            beforeFinalGuards).ConfigureAwait(false);
    }

    internal static JsonObject BuildReport(
        ReleaseAssets assets,
        FinalReportProvenanceFacts provenance,
        JsonObject development)
    {
        ArgumentNullException.ThrowIfNull(assets);
        ArgumentNullException.ThrowIfNull(provenance);
        ArgumentNullException.ThrowIfNull(development);
        if (!development.TryGetValue("cases", out var caseValue) || caseValue is not JsonArray developmentCases ||
            !development.TryGetValue("unavailable", out var unavailableValue) || unavailableValue is not JsonArray unavailable ||
            unavailable.Items.Count != 0)
        {
            throw new FinalReportProvenanceException("Final execution did not retain complete observations.");
        }

        if (developmentCases.Items.Count != assets.Cases.Count)
        {
            throw new FinalReportProvenanceException("Final execution did not retain every released case.");
        }

        var cases = new List<JsonValue>(developmentCases.Items.Count);
        for (var index = 0; index < assets.Cases.Count; index++)
        {
            if (developmentCases.Items[index] is not JsonObject observed ||
                !StringValue(observed, "id", out var id) || !string.Equals(id, assets.Cases[index].Id, StringComparison.Ordinal) ||
                !StringValue(observed, "verdict", out var verdict) || !string.Equals(verdict, "pass", StringComparison.Ordinal))
            {
                throw new FinalReportProvenanceException("Final execution contains a non-passing or unordered case.");
            }

            JsonValue evidence = JsonNull.Instance;
            if (assets.Cases[index].Kind == FixtureKind.DriverAssertion)
            {
                if (!observed.TryGetValue("observation", out var observation) || observation is not JsonObject proof ||
                    !StringValue(proof, "recipe_ref", out var recipeRef) ||
                    !string.Equals(recipeRef, assets.Cases[index].RecipeRef, StringComparison.Ordinal) ||
                    proof.Properties.Count == 0)
                {
                    throw new FinalReportProvenanceException("Final driver proof evidence is unavailable.");
                }

                evidence = new JsonObject([
                    new JsonProperty("recipe_ref", new JsonString(recipeRef)),
                    new JsonProperty("observations", proof),
                ]);
            }

            cases.Add(new JsonObject([
                new JsonProperty("id", new JsonString(id)),
                new JsonProperty("verdict", new JsonString("pass")),
                new JsonProperty("detail", JsonNull.Instance),
                new JsonProperty("evidence", evidence),
            ]));
        }

        return new JsonObject([
            new JsonProperty("report_version", new JsonString("0")),
            new JsonProperty("release", new JsonString(assets.ReleaseId)),
            new JsonProperty("release_sha256", new JsonString(assets.ReleaseSha256)),
            new JsonProperty("implementation", new JsonObject([
                new JsonProperty("name", new JsonString("anyinfer-dotnet")),
                new JsonProperty("version", new JsonString("0.1.0-proof")),
                new JsonProperty("source_revision", new JsonString(provenance.ExpectedRevision)),
                new JsonProperty("driver_revision", new JsonString(provenance.ExpectedRevision)),
                new JsonProperty("runtime", new JsonString(provenance.Runtime)),
                new JsonProperty("os", new JsonString(provenance.OperatingSystem)),
                new JsonProperty("dependencies", new JsonObject(provenance.Dependencies
                    .OrderBy(static pair => pair.Key, StringComparer.Ordinal)
                    .Select(static pair => new JsonProperty(pair.Key, new JsonString(pair.Value))))),
                new JsonProperty("extensions", new JsonArray([])),
            ])),
            new JsonProperty("cases", new JsonArray(cases)),
            new JsonProperty("counts", new JsonObject([
                new JsonProperty("pass", new JsonInteger(new BigInteger(cases.Count))),
                new JsonProperty("fail", new JsonInteger(BigInteger.Zero)),
                new JsonProperty("error", new JsonInteger(BigInteger.Zero)),
                new JsonProperty("extension", new JsonInteger(BigInteger.Zero)),
            ])),
        ]);
    }

    internal static void ValidateReport(JsonObject report, ReleaseAssets assets)
    {
        ArgumentNullException.ThrowIfNull(report);
        ArgumentNullException.ThrowIfNull(assets);
        RequireExact(report, "report_version", "release", "release_sha256", "implementation", "cases", "counts");
        if (!StringValue(report, "report_version", out var version) || version != "0" ||
            !StringValue(report, "release", out var release) || !string.Equals(release, assets.ReleaseId, StringComparison.Ordinal) ||
            !StringValue(report, "release_sha256", out var hash) || !IsLowerHash(hash) ||
            !string.Equals(hash, assets.ReleaseSha256, StringComparison.Ordinal) ||
            !ObjectValue(report, "implementation", out var implementation) || !ArrayValue(report, "cases", out var cases) || !ObjectValue(report, "counts", out var counts))
        {
            throw new FinalReportProvenanceException("Final report has an invalid root shape.");
        }

        RequireExact(implementation, "name", "version", "source_revision", "driver_revision", "runtime", "os", "dependencies", "extensions");
        if (!StringValue(implementation, "name", out var name) || name != "anyinfer-dotnet" ||
            !StringValue(implementation, "version", out var implementationVersion) || implementationVersion != "0.1.0-proof" ||
            !StringValue(implementation, "source_revision", out var sourceRevision) || !IsRevision(sourceRevision) ||
            !StringValue(implementation, "driver_revision", out var driverRevision) ||
            !string.Equals(sourceRevision, driverRevision, StringComparison.Ordinal) ||
            !StringValue(implementation, "runtime", out var runtime) || string.IsNullOrWhiteSpace(runtime) ||
            !StringValue(implementation, "os", out var operatingSystem) || string.IsNullOrWhiteSpace(operatingSystem) ||
            !ObjectValue(implementation, "dependencies", out var dependencies) ||
            !ArrayValue(implementation, "extensions", out var extensions) || extensions.Items.Count != 0)
        {
            throw new FinalReportProvenanceException("Final report implementation metadata is invalid.");
        }

        var dependencyKeys = new List<string>();
        foreach (var dependency in dependencies.Properties)
        {
            if (!dependency.Name.StartsWith("nuget:", StringComparison.Ordinal) || dependency.Name.Length == "nuget:".Length ||
                dependency.Value is not JsonString dependencyVersion || string.IsNullOrWhiteSpace(dependencyVersion.Value))
            {
                throw new FinalReportProvenanceException("Final report dependency metadata is invalid.");
            }

            dependencyKeys.Add(dependency.Name);
        }

        if (!dependencyKeys.SequenceEqual(dependencyKeys.OrderBy(static name => name, StringComparer.Ordinal), StringComparer.Ordinal))
        {
            throw new FinalReportProvenanceException("Final report dependency metadata is not ordered.");
        }

        if (cases.Items.Count != assets.Cases.Count)
        {
            throw new FinalReportProvenanceException("Final report case count is invalid.");
        }

        for (var index = 0; index < cases.Items.Count; index++)
        {
            if (cases.Items[index] is not JsonObject item ||
                item.Properties.Count != 4 || item.Properties.Any(static property => property.Name is not ("id" or "verdict" or "detail" or "evidence")) ||
                !StringValue(item, "id", out var id) ||
                !string.Equals(id, assets.Cases[index].Id, StringComparison.Ordinal) ||
                !StringValue(item, "verdict", out var verdict) || verdict != "pass" ||
                !item.TryGetValue("detail", out var detail) || detail is not JsonNull || !item.TryGetValue("evidence", out var evidence))
            {
                throw new FinalReportProvenanceException("Final report case shape is invalid.");
            }

            if (assets.Cases[index].Kind == FixtureKind.DriverAssertion)
            {
                if (evidence is not JsonObject driver || driver.Properties.Count != 2 ||
                    driver.Properties.Any(static property => property.Name is not ("recipe_ref" or "observations")) ||
                    !StringValue(driver, "recipe_ref", out var recipe) ||
                    !string.Equals(recipe, assets.Cases[index].RecipeRef, StringComparison.Ordinal) ||
                    !ObjectValue(driver, "observations", out var observations) || observations.Properties.Count == 0)
                {
                    throw new FinalReportProvenanceException("Final report driver evidence is invalid.");
                }
            }
            else if (evidence is not JsonNull)
            {
                throw new FinalReportProvenanceException("Final report fixture evidence is invalid.");
            }
        }

        RequireExact(counts, "pass", "fail", "error", "extension");
        if (!IntegerValue(counts, "pass", out var pass) || pass != cases.Items.Count ||
            !IntegerValue(counts, "fail", out var fail) || fail != 0 ||
            !IntegerValue(counts, "error", out var error) || error != 0 ||
            !IntegerValue(counts, "extension", out var extension) || extension != 0)
        {
            throw new FinalReportProvenanceException("Final report counts are invalid.");
        }
    }

    internal static async Task<string> PublishPreparedAsync(
        ReleaseAssets assets,
        FinalReportProvenanceFacts provenance,
        string destination,
        ReadOnlyMemory<byte> bytes,
        CancellationToken cancellationToken,
        Func<CancellationToken, Task>? beforeFinalGuards = null,
        FinalReportFactsObserver? observeFinalFacts = null,
        Action<string, string>? moveNoReplace = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(destination);
        FinalReportProvenance.ValidateFacts(provenance);
        ValidatePreparedBytes(bytes, assets, provenance);
        var expectedDestination = Path.Combine(provenance.RepositoryRoot, "specification", "reports", "csharp-" + provenance.ExpectedRevision[..7] + ".json");
        if (!string.Equals(Path.GetFullPath(destination), Path.GetFullPath(expectedDestination), StringComparison.OrdinalIgnoreCase))
        {
            throw new FinalReportProvenanceException("Final report destination is invalid.");
        }

        var directory = Path.GetDirectoryName(expectedDestination) ?? throw new FinalReportProvenanceException("Final report destination has no directory.");
        if (!IsContained(provenance.RepositoryRoot, expectedDestination) || File.Exists(expectedDestination) ||
            !Directory.Exists(directory) || HasReparseComponent(directory))
        {
            throw new FinalReportProvenanceException("Final report destination is unavailable.");
        }

        if (beforeFinalGuards is not null)
        {
            await beforeFinalGuards(cancellationToken).ConfigureAwait(false);
        }

        cancellationToken.ThrowIfCancellationRequested();
        var finalFacts = (observeFinalFacts ?? FinalReportProvenance.Capture)(provenance.RepositoryRoot, provenance.ExpectedRevision);
        FinalReportProvenance.ValidateFacts(finalFacts);
        EnsureSameFacts(provenance, finalFacts);
        VerifyReleaseBinding(assets);
        cancellationToken.ThrowIfCancellationRequested();

        var staging = Path.Combine(directory, ".csharp-report-" + Guid.NewGuid().ToString("N") + ".tmp");
        await using (var stream = new FileStream(staging, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, useAsync: true))
        {
            await stream.WriteAsync(bytes, cancellationToken).ConfigureAwait(false);
            await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        if (IsReparse(staging) || Directory.Exists(staging) || !File.ReadAllBytes(staging).AsSpan().SequenceEqual(bytes.Span))
        {
            throw new FinalReportProvenanceException("Final report staging is invalid.");
        }

        cancellationToken.ThrowIfCancellationRequested();
        (moveNoReplace ?? MoveNoReplace)(staging, expectedDestination);
        return expectedDestination;
    }

    private static void VerifyReleaseBinding(ReleaseAssets assets)
    {
        var verified = ReleaseAssetsReader.ReadAndVerify(assets.RootPath, assets.ReleaseRelativePath);
        if (!string.Equals(verified.ReleaseSha256, assets.ReleaseSha256, StringComparison.Ordinal) ||
            !string.Equals(verified.ReleaseId, assets.ReleaseId, StringComparison.Ordinal))
        {
            throw new FinalReportProvenanceException("Selected release binding changed.");
        }
    }

    private static void EnsureSameFacts(FinalReportProvenanceFacts initial, FinalReportProvenanceFacts final)
    {
        if (!string.Equals(initial.RepositoryRoot, final.RepositoryRoot, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(initial.ExpectedRevision, final.ExpectedRevision, StringComparison.Ordinal) ||
            !string.Equals(initial.DriverAssemblyPath, final.DriverAssemblyPath, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(initial.LoadedLibraryAssemblyPath, final.LoadedLibraryAssemblyPath, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(initial.CanonicalLibraryAssemblyPath, final.CanonicalLibraryAssemblyPath, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(initial.ObservedRevision, final.ObservedRevision, StringComparison.Ordinal) ||
            !string.Equals(initial.DriverSourceRevision, final.DriverSourceRevision, StringComparison.Ordinal) ||
            !string.Equals(initial.LibrarySourceRevision, final.LibrarySourceRevision, StringComparison.Ordinal) ||
            !initial.Dependencies.OrderBy(static pair => pair.Key, StringComparer.Ordinal).SequenceEqual(final.Dependencies.OrderBy(static pair => pair.Key, StringComparer.Ordinal)))
        {
            throw new FinalReportProvenanceException("Production provenance changed before publication.");
        }
    }

    private static void RequireExact(JsonObject value, params string[] names)
    {
        if (value.Properties.Count != names.Length || value.Properties.Any(property => !names.Contains(property.Name, StringComparer.Ordinal)))
        {
            throw new FinalReportProvenanceException("Final report has unknown or missing members.");
        }
    }

    private static bool StringValue(JsonObject value, string name, out string result)
    {
        if (value.TryGetValue(name, out var found) && found is JsonString text)
        {
            result = text.Value;
            return true;
        }

        result = string.Empty;
        return false;
    }

    private static bool ObjectValue(JsonObject value, string name, out JsonObject result)
    {
        if (value.TryGetValue(name, out var found) && found is JsonObject @object)
        {
            result = @object;
            return true;
        }

        result = null!;
        return false;
    }

    private static bool ArrayValue(JsonObject value, string name, out JsonArray result)
    {
        if (value.TryGetValue(name, out var found) && found is JsonArray array)
        {
            result = array;
            return true;
        }

        result = null!;
        return false;
    }

    private static bool IntegerValue(JsonObject value, string name, out int result)
    {
        if (value.TryGetValue(name, out var found) && found is JsonInteger integer && integer.Value >= int.MinValue && integer.Value <= int.MaxValue)
        {
            result = (int)integer.Value;
            return true;
        }

        result = 0;
        return false;
    }

    private static bool IsLowerHash(string value) => value.Length == 64 && value.All(static character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static bool IsRevision(string value) => value.Length == 40 && value.All(static character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void ValidatePreparedBytes(
        ReadOnlyMemory<byte> bytes,
        ReleaseAssets assets,
        FinalReportProvenanceFacts provenance)
    {
        try
        {
            if (JsonReader.Read(bytes.Span) is not JsonObject report)
            {
                throw new FinalReportProvenanceException("Prepared final report is invalid.");
            }

            ValidateReport(report, assets);
            ValidatePreparedProvenance(report, provenance);
            ValidateFinite(report);
        }
        catch (FormatException)
        {
            throw new FinalReportProvenanceException("Prepared final report is invalid.");
        }
    }

    private static void ValidatePreparedProvenance(JsonObject report, FinalReportProvenanceFacts provenance)
    {
        if (!ObjectValue(report, "implementation", out var implementation) ||
            !StringValue(implementation, "source_revision", out var sourceRevision) ||
            !StringValue(implementation, "driver_revision", out var driverRevision) ||
            !StringValue(implementation, "runtime", out var runtime) ||
            !StringValue(implementation, "os", out var operatingSystem) ||
            !ObjectValue(implementation, "dependencies", out var dependencies) ||
            !string.Equals(sourceRevision, provenance.ExpectedRevision, StringComparison.Ordinal) ||
            !string.Equals(driverRevision, provenance.ExpectedRevision, StringComparison.Ordinal) ||
            !string.Equals(runtime, provenance.Runtime, StringComparison.Ordinal) ||
            !string.Equals(operatingSystem, provenance.OperatingSystem, StringComparison.Ordinal))
        {
            throw new FinalReportProvenanceException("Prepared final report provenance is invalid.");
        }

        var prepared = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var dependency in dependencies.Properties)
        {
            if (dependency.Value is not JsonString version || string.IsNullOrWhiteSpace(version.Value) ||
                !IsCanonicalPackageKey(dependency.Name) ||
                !prepared.TryAdd(dependency.Name, version.Value))
            {
                throw new FinalReportProvenanceException("Prepared final report provenance is invalid.");
            }
        }

        if (!prepared.SequenceEqual(provenance.Dependencies.OrderBy(static pair => pair.Key, StringComparer.Ordinal)))
        {
            throw new FinalReportProvenanceException("Prepared final report provenance is invalid.");
        }
    }

    private static bool IsCanonicalPackageKey(string value)
    {
        const string prefix = "nuget:";
        if (!value.StartsWith(prefix, StringComparison.Ordinal) || value.Length == prefix.Length ||
            !string.Equals(value, value.ToLowerInvariant(), StringComparison.Ordinal))
        {
            return false;
        }

        return value[prefix.Length..].All(static character =>
            character is >= 'a' and <= 'z' or >= '0' and <= '9' or '_' or '.' or '-');
    }

    private static void ValidateFinite(JsonValue value)
    {
        switch (value)
        {
            case JsonNumber number when !double.IsFinite(number.Value):
                throw new FinalReportProvenanceException("Prepared final report is invalid.");
            case JsonArray array:
                foreach (var item in array.Items)
                {
                    ValidateFinite(item);
                }

                break;
            case JsonObject @object:
                foreach (var property in @object.Properties)
                {
                    ValidateFinite(property.Value);
                }

                break;
        }
    }

    private static bool IsContained(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        return !Path.IsPathFullyQualified(relative) && relative != ".." &&
               !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) &&
               !relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal);
    }

    private static bool IsReparse(string path) => (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;

    private static void MoveNoReplace(string source, string destination)
    {
        File.Move(source, destination, overwrite: false);
    }

    private static bool HasReparseComponent(string path)
    {
        var current = Path.GetPathRoot(path) ?? string.Empty;
        foreach (var part in path[current.Length..].Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
        {
            if (part.Length == 0)
            {
                continue;
            }

            current = Path.Combine(current, part);
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
            {
                return true;
            }
        }

        return false;
    }
}
