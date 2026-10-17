using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Json;
using Xunit;
using JsonProperty = AnyInfer.Json.JsonProperty;

namespace AnyInfer.Conformance;

/// <summary>Independent no-publish checks for the final native proof report guards.</summary>
public sealed class FinalReportTests : IDisposable
{
    private readonly List<string> _temporaryRoots = [];
    private static readonly Lazy<Task<JsonObject>> CompleteDevelopment = new(static async () =>
        await ReportWriter.RunDevelopmentAsync(ReadSourceAssets()).ConfigureAwait(false));

    [Fact]
    public void Immutable_provenance_rejects_stale_foreign_dirty_and_conflicting_facts()
    {
        var facts = CreateProvenanceLayout().Facts;
        FinalReportProvenance.ValidateFacts(facts);

        var foreign = facts with { DriverAssemblyPath = Path.Combine(Path.GetTempPath(), "foreign-driver.dll") };
        var foreignLibrary = facts with { LoadedLibraryAssemblyPath = Path.Combine(Path.GetTempPath(), "foreign-library.dll") };
        var stale = facts with { ObservedRevision = new string('0', 40) };
        var dirty = facts with { IsClean = false };
        var mismatchedDriver = facts with { DriverSourceRevision = new string('1', 40) };
        var mismatchedLibrary = facts with { LibrarySourceRevision = new string('2', 40) };
        var dependencyConflict = facts with
        {
            Dependencies = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["not-nuget"] = "1.0.0",
            },
        };

        Assert.All(new[] { foreign, foreignLibrary, stale, dirty, mismatchedDriver, mismatchedLibrary, dependencyConflict }, static candidate =>
            Assert.Throws<FinalReportProvenanceException>(() => FinalReportProvenance.ValidateFacts(candidate)));
    }

    [Fact]
    public void Immutable_provenance_requires_the_standard_driver_library_layout_and_equal_library_copy()
    {
        var layout = CreateProvenanceLayout();
        FinalReportProvenance.ValidateFacts(layout.Facts);

        var foreignDriver = layout.Facts with { DriverAssemblyPath = Path.Combine(layout.Root, "foreign", "AnyInfer.Conformance.dll") };
        Directory.CreateDirectory(Path.GetDirectoryName(foreignDriver.DriverAssemblyPath)!);
        File.Copy(layout.Facts.DriverAssemblyPath, foreignDriver.DriverAssemblyPath);
        Assert.Throws<FinalReportProvenanceException>(() => FinalReportProvenance.ValidateFacts(foreignDriver));

        File.WriteAllBytes(layout.Facts.LoadedLibraryAssemblyPath, Encoding.UTF8.GetBytes("not-the-canonical-library"));
        var copiedLibraryMismatch = layout.Facts;
        var missingRevision = layout.Facts with { LibrarySourceRevision = string.Empty };

        Assert.All(new[] { copiedLibraryMismatch, missingRevision }, static candidate =>
            Assert.Throws<FinalReportProvenanceException>(() => FinalReportProvenance.ValidateFacts(candidate)));
    }

    [Fact]
    public void Package_catalog_resolution_uses_only_net8_package_targets_and_rejects_malformed_or_conflicting_catalogs()
    {
        using var malformed = JsonDocument.Parse("{\"libraries\":{}}");
        using var conflict = JsonDocument.Parse("""
            {"targets":{"net8.0":{"Xunit/1.0":{"type":"package"},"xunit/2.0":{"type":"package"}}},"libraries":{"Xunit/1.0":{"type":"package"},"xunit/2.0":{"type":"package"}}}
            """);
        using var targetCatalogMismatch = JsonDocument.Parse("""
            {"targets":{"net8.0":{"xunit/2.9.3":{"type":"package"}}},"libraries":{"xunit/2.9.3":{"type":"project"}}}
            """);
        using var irrelevant = JsonDocument.Parse("""
            {"targets":{"net8.0":{"AnyInfer/0.1.0":{"type":"project"},"my_package/1.0.0":{"type":"package"},"xunit/2.9.3":{"type":"package"}},"net7.0":{"different/9.0":{"type":"package"}}},"libraries":{"AnyInfer/0.1.0":{"type":"project"},"my_package/1.0.0":{"type":"package"},"xunit/2.9.3":{"type":"package"},"different/9.0":{"type":"package"}}}
            """);

        Assert.Throws<FinalReportProvenanceException>(() => FinalReportProvenance.ReadPackageVersions(malformed.RootElement));
        Assert.Throws<FinalReportProvenanceException>(() => FinalReportProvenance.ReadPackageVersions(conflict.RootElement));
        Assert.Throws<FinalReportProvenanceException>(() => FinalReportProvenance.ReadPackageVersions(targetCatalogMismatch.RootElement));
        var packages = FinalReportProvenance.ReadPackageVersions(irrelevant.RootElement);
        Assert.True(packages.Count == 2);
        Assert.Equal("1.0.0", packages["nuget:my_package"]);
        Assert.Equal("2.9.3", packages["nuget:xunit"]);
    }

    [Fact]
    public async Task Build_report_from_real_complete_development_execution_is_anchored_to_executable_provenance()
    {
        var assets = ReadSourceAssets();
        var provenance = CreateProvenanceLayout().Facts;
        var development = await CompleteDevelopment.Value;

        var report = FinalReportWriter.BuildReport(assets, provenance, development);
        FinalReportWriter.ValidateReport(report, assets);

        Assert.Equal(provenance.ExpectedRevision, String(report, "implementation", "source_revision"));
        Assert.Equal(assets.Cases.Count, Assert.IsType<JsonArray>(Value(report, "cases")).Items.Count);
        Assert.Empty(Assert.IsType<JsonArray>(Value(development, "unavailable")).Items);
        Assert.Equal("0", StringValue(report, "report_version"));
        Assert.Equal("anyinfer-dotnet", String(report, "implementation", "name"));
        Assert.Empty(Assert.IsType<JsonArray>(Value(Object(report, "implementation"), "extensions")).Items);
        foreach (var (caseDefinition, item) in assets.Cases.Zip(Assert.IsType<JsonArray>(Value(report, "cases")).Items))
        {
            var reportCase = Assert.IsType<JsonObject>(item);
            if (caseDefinition.Kind == FixtureKind.Fixture)
            {
                Assert.IsType<JsonNull>(Value(reportCase, "evidence"));
            }
            else
            {
                Assert.IsType<JsonObject>(Value(Assert.IsType<JsonObject>(Value(reportCase, "evidence")), "observations"));
            }
        }

        var bytes = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false).GetBytes(JsonWriter.Write(report) + "\n");
        Assert.False(bytes.AsSpan().StartsWith(Encoding.UTF8.GetPreamble()));
    }

    [Fact]
    public async Task Final_report_refuses_incomplete_unavailable_nonpassing_and_missing_driver_evidence()
    {
        var assets = ReadSourceAssets();
        var development = await CompleteDevelopment.Value;
        var facts = CreateProvenanceLayout().Facts;

        var unavailable = WithProperty(development, "unavailable", new JsonArray([new JsonString("driver/unavailable")]));
        var failedCases = WithItem(
            Assert.IsType<JsonArray>(Value(development, "cases")),
            0,
            WithProperty(Assert.IsType<JsonObject>(Assert.IsType<JsonArray>(Value(development, "cases")).Items[0]), "verdict", new JsonString("fail")));
        var failed = WithProperty(development, "cases", failedCases);
        var driverIndex = assets.Cases.ToList().FindIndex(static item => item.Kind == FixtureKind.DriverAssertion);
        Assert.True(driverIndex >= 0);
        var withoutEvidenceCases = WithItem(
            Assert.IsType<JsonArray>(Value(development, "cases")),
            driverIndex,
            Without(Assert.IsType<JsonObject>(Assert.IsType<JsonArray>(Value(development, "cases")).Items[driverIndex]), "observation"));
        var withoutEvidence = WithProperty(development, "cases", withoutEvidenceCases);

        Assert.All(new[] { unavailable, failed, withoutEvidence }, candidate =>
            Assert.Throws<FinalReportProvenanceException>(() => FinalReportWriter.BuildReport(assets, facts, candidate)));
    }

    [Fact]
    public async Task Report_validator_rejects_wrong_bindings_metadata_and_closed_case_evidence()
    {
        var assets = ReadSourceAssets();
        var report = FinalReportWriter.BuildReport(assets, CreateProvenanceLayout().Facts, await CompleteDevelopment.Value);
        FinalReportWriter.ValidateReport(report, assets);

        var unknown = WithProperty(report, "foreign", new JsonString("x"));
        var wrongHash = WithProperty(report, "release_sha256", new JsonString(new string('a', 64)));
        var counts = WithProperty(Object(report, "counts"), "pass", new JsonInteger(0));
        var wrongCounts = WithProperty(report, "counts", counts);
        var cases = Assert.IsType<JsonArray>(Value(report, "cases"));
        var nonNullFixture = WithProperty(Assert.IsType<JsonObject>(cases.Items[0]), "evidence", new JsonObject([]));
        var wrongEvidence = WithProperty(report, "cases", WithItem(cases, 0, nonNullFixture));
        var unknownCaseMember = WithProperty(report, "cases", WithItem(cases, 0,
            WithProperty(Assert.IsType<JsonObject>(cases.Items[0]), "foreign", new JsonString("x"))));
        var implementation = Object(report, "implementation");
        var wrongSourceRevision = WithProperty(report, "implementation", WithProperty(implementation, "source_revision", new JsonString(new string('a', 40))));
        var wrongDriverRevision = WithProperty(report, "implementation", WithProperty(implementation, "driver_revision", new JsonString(new string('b', 40))));
        var blankRuntime = WithProperty(report, "implementation", WithProperty(implementation, "runtime", new JsonString("")));
        var nonStringOperatingSystem = WithProperty(report, "implementation", WithProperty(implementation, "os", new JsonInteger(1)));
        var invalidDependency = WithProperty(report, "implementation", WithProperty(implementation, "dependencies", new JsonObject([
            new JsonProperty("invalid", new JsonString("1.0.0")),
        ])));
        var driverIndex = assets.Cases.ToList().FindIndex(static item => item.Kind == FixtureKind.DriverAssertion);
        Assert.True(driverIndex >= 0);
        var driverCase = Assert.IsType<JsonObject>(cases.Items[driverIndex]);
        var driverEvidence = Object(driverCase, "evidence");
        var unknownWrapper = WithProperty(report, "cases", WithItem(cases, driverIndex, WithProperty(driverCase, "evidence", WithProperty(driverEvidence, "foreign", new JsonString("x")))));
        var missingObservations = WithProperty(report, "cases", WithItem(cases, driverIndex, WithProperty(driverCase, "evidence", Without(driverEvidence, "observations"))));
        var emptyObservations = WithProperty(report, "cases", WithItem(cases, driverIndex, WithProperty(driverCase, "evidence", WithProperty(driverEvidence, "observations", new JsonObject([])))));

        Assert.All(new[]
        {
            unknown, wrongHash, wrongCounts, wrongEvidence, unknownCaseMember, wrongSourceRevision, wrongDriverRevision,
            blankRuntime, nonStringOperatingSystem, invalidDependency, unknownWrapper, missingObservations, emptyObservations,
        }, candidate =>
            Assert.Throws<FinalReportProvenanceException>(() => FinalReportWriter.ValidateReport(candidate, assets)));
    }

    [Fact]
    public async Task Publisher_never_replaces_existing_target_or_stages_after_prepublication_cancellation()
    {
        var assets = ReadSourceAssets();
        var facts = CreateProvenanceLayout().Facts;
        var bytes = await PreparedBytes(assets, facts);
        var destination = CanonicalDestination(facts);
        var directory = Path.GetDirectoryName(destination)!;
        var original = Encoding.UTF8.GetBytes("existing\n");

        var nonCanonical = Path.Combine(directory, "candidate.json");
        var outside = Path.Combine(CreateSandbox(), "csharp-" + facts.ExpectedRevision[..7] + ".json");
        var invalidInside = await Assert.ThrowsAsync<FinalReportProvenanceException>(() =>
            FinalReportWriter.PublishPreparedAsync(assets, facts, nonCanonical, bytes, CancellationToken.None));
        var invalidOutside = await Assert.ThrowsAsync<FinalReportProvenanceException>(() =>
            FinalReportWriter.PublishPreparedAsync(assets, facts, outside, bytes, CancellationToken.None));
        Assert.Equal("Final report destination is invalid.", invalidInside.Message);
        Assert.Equal("Final report destination is invalid.", invalidOutside.Message);
        Assert.False(File.Exists(nonCanonical));
        Assert.False(File.Exists(outside));

        await File.WriteAllBytesAsync(destination, original);

        var existing = await Assert.ThrowsAsync<FinalReportProvenanceException>(() =>
            FinalReportWriter.PublishPreparedAsync(assets, facts, destination, bytes, CancellationToken.None, observeFinalFacts: static (_, _) => throw new InvalidOperationException("Existing output must refuse before final facts.")));
        Assert.Equal("Final report destination is unavailable.", existing.Message);
        Assert.Equal(original, await File.ReadAllBytesAsync(destination));

        File.Delete(destination);
        using var cancellation = new CancellationTokenSource();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => FinalReportWriter.PublishPreparedAsync(
            assets,
            facts,
            destination,
            bytes,
            cancellation.Token,
            token =>
            {
                cancellation.Cancel();
                token.ThrowIfCancellationRequested();
                return Task.CompletedTask;
            },
            static (_, _) => throw new InvalidOperationException("Cancellation must precede final-facts observation.")));
        Assert.False(File.Exists(destination));
        Assert.Empty(Directory.EnumerateFiles(directory, ".csharp-report-*.tmp", SearchOption.TopDirectoryOnly));

        await Assert.ThrowsAsync<IOException>(() => FinalReportWriter.PublishPreparedAsync(
            assets,
            facts,
            destination,
            bytes,
            CancellationToken.None,
            _ =>
            {
                File.WriteAllBytes(destination, original);
                return Task.CompletedTask;
            },
            (_, _) => facts));
        Assert.Equal(original, await File.ReadAllBytesAsync(destination));
    }

    [Fact]
    public async Task Publisher_revalidates_the_selected_release_before_staging_or_publication()
    {
        var specification = CopySpecificationRoot();
        var assets = ReleaseAssetsReader.ReadAndVerify(specification, "releases/core-generation-v0.json");
        var facts = CreateProvenanceLayout().Facts;
        var destination = CanonicalDestination(facts);
        var bytes = await PreparedBytes(assets, facts);

        var changed = await Assert.ThrowsAsync<FinalReportProvenanceException>(() => FinalReportWriter.PublishPreparedAsync(
            assets,
            facts,
            destination,
            bytes,
            CancellationToken.None,
            _ =>
            {
                File.AppendAllText(Path.Combine(specification, "releases", "core-generation-v0.json"), " \n", new UTF8Encoding(false));
                return Task.CompletedTask;
            },
            (_, _) => facts));

        Assert.Equal("Selected release binding changed.", changed.Message);
        Assert.False(File.Exists(destination));
        Assert.Empty(Directory.EnumerateFiles(Path.GetDirectoryName(destination)!, ".csharp-report-*.tmp"));
    }

    [Fact]
    public async Task Publisher_writes_one_new_canonical_sandbox_report_with_exact_bytes_and_no_staging_leftover()
    {
        var copiedSpecification = CopySpecificationRoot();
        var assets = ReleaseAssetsReader.ReadAndVerify(copiedSpecification, "releases/core-generation-v0.json");
        var facts = CreateProvenanceLayout().Facts;
        var bytes = await PreparedBytes(assets, facts);
        var destination = CanonicalDestination(facts);

        var written = await FinalReportWriter.PublishPreparedAsync(
            assets,
            facts,
            destination,
            bytes,
            CancellationToken.None,
            observeFinalFacts: (_, _) => facts);

        Assert.Equal(destination, written);
        Assert.Equal(bytes.ToArray(), await File.ReadAllBytesAsync(destination));
        Assert.Empty(Directory.EnumerateFiles(Path.GetDirectoryName(destination)!, ".csharp-report-*.tmp"));
        Assert.False(File.Exists(Path.Combine(copiedSpecification, "reports", Path.GetFileName(destination))));
    }

    [Fact]
    public async Task Publisher_refuses_missing_or_reparse_canonical_reports_directory_before_hook_or_staging()
    {
        var assets = ReadSourceAssets();
        var missing = CreateProvenanceLayout().Facts;
        var bytes = await PreparedBytes(assets, missing);
        var missingDirectory = Path.GetDirectoryName(CanonicalDestination(missing))!;
        Directory.Delete(missingDirectory, recursive: true);
        var hookCalled = false;
        var missingFailure = await Assert.ThrowsAsync<FinalReportProvenanceException>(() => FinalReportWriter.PublishPreparedAsync(
            assets, missing, CanonicalDestination(missing), bytes, CancellationToken.None,
            _ =>
            {
                hookCalled = true;
                return Task.CompletedTask;
            },
            (_, _) => missing));
        Assert.Equal("Final report destination is unavailable.", missingFailure.Message);
        Assert.False(hookCalled);

        var reparse = CreateProvenanceLayout().Facts;
        var reports = Path.GetDirectoryName(CanonicalDestination(reparse))!;
        var target = CreateSandbox();
        Directory.Delete(reports, recursive: true);
        try
        {
            _ = Directory.CreateSymbolicLink(reports, target);
            var reparseFailure = await Assert.ThrowsAsync<FinalReportProvenanceException>(() => FinalReportWriter.PublishPreparedAsync(
                assets, reparse, CanonicalDestination(reparse), bytes, CancellationToken.None,
                observeFinalFacts: (_, _) => reparse));
            Assert.Equal("Final report destination is unavailable.", reparseFailure.Message);
            Assert.False(File.Exists(CanonicalDestination(reparse)));
        }
        catch (IOException exception) when (OperatingSystem.IsWindows() && (exception.HResult & 0xffff) == 1314)
        {
            // Windows symlink creation needs a developer-mode or elevated capability which this test host lacks.
        }
        catch (PlatformNotSupportedException)
        {
            // This platform does not expose directory reparse points to the managed test host.
        }
    }

    [Fact]
    public async Task Publisher_retains_an_ambiguous_stage_after_a_final_atomic_move_failure_without_creating_the_report()
    {
        var assets = ReadSourceAssets();
        var facts = CreateProvenanceLayout().Facts;
        var bytes = await PreparedBytes(assets, facts);
        var destination = CanonicalDestination(facts);
        string? observedStage = null;
        var retained = Encoding.UTF8.GetBytes("unknown-stage-bytes");

        await Assert.ThrowsAsync<IOException>(() => FinalReportWriter.PublishPreparedAsync(
            assets,
            facts,
            destination,
            bytes,
            CancellationToken.None,
            observeFinalFacts: (_, _) => facts,
            moveNoReplace: (stage, _) =>
            {
                Assert.True(File.Exists(stage));
                observedStage = stage;
                File.WriteAllBytes(stage, retained);
                throw new IOException("controlled move failure");
            }));

        Assert.False(File.Exists(destination));
        Assert.NotNull(observedStage);
        Assert.Equal(retained, await File.ReadAllBytesAsync(observedStage!));
    }

    [Fact]
    public async Task Publisher_binds_prepared_metadata_to_the_same_valid_sandbox_facts_before_hook_or_staging()
    {
        var assets = ReadSourceAssets();
        var facts = CreateProvenanceLayout().Facts with
        {
            Dependencies = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["nuget:xunit"] = "2.9.3",
            },
        };
        FinalReportProvenance.ValidateFacts(facts);
        var report = FinalReportWriter.BuildReport(assets, facts, await CompleteDevelopment.Value);
        var implementation = Object(report, "implementation");
        var replacementRevision = new string('c', 40);
        var revisionMismatch = WithProperty(report, "implementation", WithProperty(
            WithProperty(implementation, "source_revision", new JsonString(replacementRevision)),
            "driver_revision",
            new JsonString(replacementRevision)));
        var runtimeMismatch = WithProperty(report, "implementation", WithProperty(implementation, "runtime", new JsonString("other-runtime")));
        var operatingSystemMismatch = WithProperty(report, "implementation", WithProperty(implementation, "os", new JsonString("other-os")));
        var versionMismatch = WithProperty(report, "implementation", WithProperty(implementation, "dependencies", new JsonObject([
            new JsonProperty("nuget:xunit", new JsonString("9.9.9")),
        ])));
        var casingAndDuplicateIdentity = WithProperty(report, "implementation", WithProperty(implementation, "dependencies", new JsonObject([
            new JsonProperty("nuget:Xunit", new JsonString("2.9.3")),
            new JsonProperty("nuget:xunit", new JsonString("2.9.3")),
        ])));
        var destination = CanonicalDestination(facts);

        foreach (var candidate in new[] { revisionMismatch, runtimeMismatch, operatingSystemMismatch, versionMismatch, casingAndDuplicateIdentity })
        {
            var hookCalled = false;
            var exception = await Assert.ThrowsAsync<FinalReportProvenanceException>(() => FinalReportWriter.PublishPreparedAsync(
                assets,
                facts,
                destination,
                PreparedBytes(candidate),
                CancellationToken.None,
                _ =>
                {
                    hookCalled = true;
                    return Task.CompletedTask;
                },
                (_, _) => throw new InvalidOperationException("Prepared metadata must reject before final observation.")));
            Assert.Equal("Prepared final report provenance is invalid.", exception.Message);
            Assert.False(hookCalled);
            Assert.False(File.Exists(destination));
            Assert.Empty(Directory.EnumerateFiles(Path.GetDirectoryName(destination)!, ".csharp-report-*.tmp"));
        }
    }

    public void Dispose()
    {
        foreach (var root in _temporaryRoots)
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private (string Root, FinalReportProvenanceFacts Facts) CreateProvenanceLayout()
    {
        var root = CreateSandbox();
        var driverDirectory = Path.Combine(root, "src", "csharp", "AnyInfer.Conformance", "bin", "Debug", "net8.0");
        var canonicalDirectory = Path.Combine(root, "src", "csharp", "AnyInfer", "bin", "Debug", "net8.0");
        Directory.CreateDirectory(driverDirectory);
        Directory.CreateDirectory(canonicalDirectory);
        Directory.CreateDirectory(Path.Combine(root, "specification", "reports"));
        var driver = Path.Combine(driverDirectory, "AnyInfer.Conformance.dll");
        var copiedLibrary = Path.Combine(driverDirectory, "AnyInfer.dll");
        var canonicalLibrary = Path.Combine(canonicalDirectory, "AnyInfer.dll");
        File.Copy(typeof(Program).Assembly.Location, driver);
        File.Copy(typeof(AsyncClient).Assembly.Location, copiedLibrary);
        File.Copy(typeof(AsyncClient).Assembly.Location, canonicalLibrary);
        var revision = FinalReportProvenance.CurrentRevision(FindRepositoryRoot());
        return (root, new FinalReportProvenanceFacts(
            root,
            revision,
            revision,
            true,
            driver,
            copiedLibrary,
            canonicalLibrary,
            revision,
            revision,
            System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            System.Runtime.InteropServices.RuntimeInformation.OSDescription,
            new Dictionary<string, string>(StringComparer.Ordinal)));
    }

    private static async Task<ReadOnlyMemory<byte>> PreparedBytes(ReleaseAssets assets, FinalReportProvenanceFacts facts)
    {
        var development = await CompleteDevelopment.Value;
        var report = FinalReportWriter.BuildReport(assets, facts, development);
        FinalReportWriter.ValidateReport(report, assets);
        return PreparedBytes(report);
    }

    private static ReadOnlyMemory<byte> PreparedBytes(JsonObject report) =>
        new UTF8Encoding(encoderShouldEmitUTF8Identifier: false).GetBytes(JsonWriter.Write(report) + "\n");

    private static string CanonicalDestination(FinalReportProvenanceFacts facts) =>
        Path.Combine(facts.RepositoryRoot, "specification", "reports", "csharp-" + facts.ExpectedRevision[..7] + ".json");

    private static ReleaseAssets ReadSourceAssets() =>
        ReleaseAssetsReader.ReadAndVerify(Path.Combine(FindRepositoryRoot(), "specification"), "releases/core-generation-v0.json");

    private string CreateSandbox()
    {
        var sandbox = Path.Combine(FindRepositoryRoot(), ".tmp-tests", "final-report-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(sandbox);
        _temporaryRoots.Add(sandbox);
        return sandbox;
    }

    private string CopySpecificationRoot()
    {
        var source = Path.Combine(FindRepositoryRoot(), "specification");
        var destination = Path.Combine(FindRepositoryRoot(), ".tmp-tests", "final-report-assets-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source, "*", SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(Path.Combine(destination, Path.GetRelativePath(source, directory)));
        }

        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            File.Copy(file, Path.Combine(destination, Path.GetRelativePath(source, file)));
        }

        _temporaryRoots.Add(destination);
        return destination;
    }

    private static string FindRepositoryRoot()
    {
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            if (File.Exists(Path.Combine(current.FullName, "AnyInfer.sln")))
            {
                var root = Path.GetFullPath(Path.Combine(current.FullName, "..", ".."));
                if (File.Exists(Path.Combine(root, "specification", "releases", "core-generation-v0.json")))
                {
                    return root;
                }
            }
        }

        throw new InvalidOperationException("The executable repository root could not be located.");
    }

    private static JsonObject WithProperty(JsonObject source, string name, JsonValue value)
    {
        var found = false;
        var properties = source.Properties.Select(property =>
        {
            if (!string.Equals(property.Name, name, StringComparison.Ordinal))
            {
                return property;
            }

            found = true;
            return new JsonProperty(name, value);
        }).ToList();
        if (!found)
        {
            properties.Add(new JsonProperty(name, value));
        }

        return new JsonObject(properties);
    }

    private static JsonObject Without(JsonObject source, string name) =>
        new(source.Properties.Where(property => !string.Equals(property.Name, name, StringComparison.Ordinal)));

    private static JsonArray WithItem(JsonArray source, int index, JsonValue replacement) =>
        new(source.Items.Select((item, current) => current == index ? replacement : item));

    private static JsonValue Value(JsonObject source, string name)
    {
        Assert.True(source.TryGetValue(name, out var value), "Missing JSON member: " + name);
        return value;
    }

    private static JsonObject Object(JsonObject source, string name) => Assert.IsType<JsonObject>(Value(source, name));

    private static string String(JsonObject source, string first, string second) =>
        Assert.IsType<JsonString>(Value(Object(source, first), second)).Value;

    private static string StringValue(JsonObject source, string name) =>
        Assert.IsType<JsonString>(Value(source, name)).Value;
}
