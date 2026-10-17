using System.Diagnostics;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace AnyInfer.Conformance;

public sealed class ReleaseAssetsTests : IDisposable
{
    private readonly List<string> _temporaryRoots = [];

    [Fact]
    public void Selected_alternate_root_is_closed_ordered_and_ignores_a_later_unlisted_file()
    {
        var root = CopySpecificationRoot();
        File.WriteAllText(Path.Combine(root, "fixtures", "core-generation", "future-unlisted.json"), "{\"future\":true}\n", new UTF8Encoding(false));

        var assets = ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json");

        Assert.Equal(root, assets.RootPath);
        Assert.Equal("releases/core-generation-v0.json", assets.ReleaseRelativePath);
        Assert.Equal("core-generation-v0", assets.ReleaseId);
        Assert.Equal("core-generation", assets.Profile);
        Assert.Equal("v0", assets.ProfileRevision);
        Assert.Equal(106, assets.Files.Count);
        Assert.Equal(102, assets.Cases.Count);
        Assert.Equal(96, assets.Cases.Count(static item => item.Kind == FixtureKind.Fixture));
        Assert.Equal(assets.Cases.Count, assets.Cases.Select(static item => item.Id).Distinct(StringComparer.Ordinal).Count());
        Assert.DoesNotContain(assets.Files, static item => item.RelativePath.EndsWith("future-unlisted.json", StringComparison.Ordinal));
        Assert.All(assets.Files, static item => Assert.True(item.Bytes.Length > 0));
        Assert.Equal(
            assets.Files.Select(static item => item.RelativePath).OrderBy(static path => path, StringComparer.Ordinal),
            assets.Files.Select(static item => item.RelativePath));
    }

    [Theory]
    [InlineData("releases\\core-generation-v0.json")]
    [InlineData("releases//core-generation-v0.json")]
    [InlineData("./releases/core-generation-v0.json")]
    [InlineData("../releases/core-generation-v0.json")]
    [InlineData("C:/outside.json")]
    [InlineData("/outside.json")]
    public void Release_reader_rejects_unsafe_or_aliased_release_paths(string releasePath)
    {
        var root = CopySpecificationRoot();
        var failure = Assert.Throws<AssetValidationException>(() => ReleaseAssetsReader.ReadAndVerify(root, releasePath));
        Assert.Equal("path", failure.Category);
    }

    [Fact]
    public void Release_reader_reports_case_only_release_aliases_separately()
    {
        var root = CopySpecificationRoot();
        var failure = Assert.Throws<AssetValidationException>(() =>
            ReleaseAssetsReader.ReadAndVerify(root, "releases/Core-Generation-v0.json"));
        Assert.Equal("path_alias", failure.Category);
    }

    [Fact]
    public void Release_reader_requires_an_absolute_non_reparse_selected_root()
    {
        var relativeFailure = Assert.Throws<AssetValidationException>(() =>
            ReleaseAssetsReader.ReadAndVerify("specification", "releases/core-generation-v0.json"));
        Assert.Equal("root", relativeFailure.Category);

        var missingFailure = Assert.Throws<AssetValidationException>(() =>
            ReleaseAssetsReader.ReadAndVerify(Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N")), "releases/core-generation-v0.json"));
        Assert.Equal("root", missingFailure.Category);
    }

    [Fact]
    public void Release_reader_rejects_selected_root_and_final_file_reparse_points_when_supported()
    {
        var root = CopySpecificationRoot();
        var link = root + "-link";
        try
        {
            Directory.CreateSymbolicLink(link, root);
            _temporaryRoots.Add(link);
            var rootFailure = Assert.Throws<AssetValidationException>(() =>
                ReleaseAssetsReader.ReadAndVerify(link, "releases/core-generation-v0.json"));
            Assert.Equal("reparse_point", rootFailure.Category);

            var readme = Path.Combine(root, "README.md");
            var target = Path.Combine(root, "README-target.md");
            File.Move(readme, target);
            File.CreateSymbolicLink(readme, target);
            var fileFailure = Assert.Throws<AssetValidationException>(() =>
                ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json"));
            Assert.Equal("reparse_point", fileFailure.Category);
        }
        catch (UnauthorizedAccessException)
        {
            // Native link creation is policy-dependent; the reader path is covered when available.
        }
        catch (IOException)
        {
            // Native link creation is policy-dependent; the reader path is covered when available.
        }
    }

    [Fact]
    public void Release_reader_rejects_tampering_missing_and_extra_closed_file_entries()
    {
        var tamperedRoot = CopySpecificationRoot();
        File.AppendAllText(Path.Combine(tamperedRoot, "README.md"), "tampered\n", new UTF8Encoding(false));
        AssertAssetFailure(tamperedRoot, "hash_mismatch", "specification/README.md");

        var missingRoot = CopySpecificationRoot();
        MutateRelease(missingRoot, release => release["files"]!.AsObject().Remove("specification/README.md"));
        AssertAssetFailure(missingRoot, "release_files", "releases/core-generation-v0.json");

        var extraRoot = CopySpecificationRoot();
        File.WriteAllText(Path.Combine(extraRoot, "future.md"), "future\n", new UTF8Encoding(false));
        MutateRelease(extraRoot, release => release["files"]!.AsObject().Add("specification/future.md", Sha256(File.ReadAllBytes(Path.Combine(extraRoot, "future.md")))));
        AssertAssetFailure(extraRoot, "release_files", "releases/core-generation-v0.json");
    }

    [Fact]
    public void Release_reader_rejects_mismatched_duplicate_and_nonordinary_case_metadata()
    {
        var mismatchRoot = CopySpecificationRoot();
        MutateRelease(mismatchRoot, release => release["case_inventory"]!.AsArray()[0]!.AsObject()["id"] = "wrong/id");
        AssertAssetFailure(mismatchRoot, "case_inventory", "releases/core-generation-v0.json");

        var duplicateRoot = CopySpecificationRoot();
        MutateRelease(duplicateRoot, release =>
        {
            var cases = release["case_inventory"]!.AsArray();
            cases.Add(cases[0]!.DeepClone());
        });
        AssertAssetFailure(duplicateRoot, "case_inventory", "releases/core-generation-v0.json");

        var malformedRoot = CopySpecificationRoot();
        File.WriteAllBytes(Path.Combine(malformedRoot, "releases", "core-generation-v0.json"), [0xff, 0xfe, 0xfd]);
        AssertAssetFailure(malformedRoot, "release_json", "releases/core-generation-v0.json");
    }

    [Fact]
    public void Release_reader_rejects_reference_environment_hash_and_revision_binding_mutations_after_rehashing_metadata()
    {
        var environmentRoot = CopySpecificationRoot();
        var referencePath = Path.Combine(environmentRoot, "reference", "python-fc53787.json");
        MutateJson(referencePath, document => document["environment"]!.AsObject()["sha256"] = new string('0', 64));
        RehashReleaseEntry(environmentRoot, "specification/reference/python-fc53787.json");
        AssertAssetFailure(environmentRoot, "environment_hash", "specification/reference/python-fc53787.environment.json");

        var revisionRoot = CopySpecificationRoot();
        var revisionPath = Path.Combine(revisionRoot, "reference", "python-fc53787.json");
        MutateJson(revisionPath, document => document["reference_run_revision"] = "bad");
        RehashReleaseEntry(revisionRoot, "specification/reference/python-fc53787.json");
        AssertAssetFailure(revisionRoot, "revision", "specification/reference/python-fc53787.json");
    }

    [Fact]
    public void Release_reader_rejects_self_consistent_inventory_and_historical_reference_mutations()
    {
        var profileRoot = CopySpecificationRoot();
        MutateInventory(profileRoot, inventory => inventory["profile"] = "other-profile");
        AssertAnyAssetFailure(profileRoot, "specification/inventories/core-generation-v0.json");

        var revisionRoot = CopySpecificationRoot();
        MutateInventory(revisionRoot, inventory => inventory["profile_revision"] = "other-revision");
        AssertAnyAssetFailure(revisionRoot, "specification/inventories/core-generation-v0.json");

        var requirementRoot = CopySpecificationRoot();
        MutateInventory(requirementRoot, inventory => inventory["requirements"]!.AsArray()[0]!.AsObject()["case_ids"] = new JsonArray("missing/case"));
        AssertAnyAssetFailure(requirementRoot, "specification/inventories/core-generation-v0.json");

        var caseRoot = CopySpecificationRoot();
        MutateInventoryAndReleaseCase(caseRoot, "driver/assessment-completeness", (inventoryCase, releaseCase) =>
        {
            inventoryCase["family"] = "not-driver";
            releaseCase["family"] = "not-driver";
        });
        AssertAnyAssetFailure(caseRoot, "specification/inventories/core-generation-v0.json");

        var extensionRoot = CopySpecificationRoot();
        MutateInventoryAndReleaseCase(extensionRoot, "validation/type-mismatch-string-for-integer", (inventoryCase, releaseCase) =>
        {
            inventoryCase["extension"] = "schema.not-declared";
            releaseCase["extension"] = "schema.not-declared";
        });
        AssertAnyAssetFailure(extensionRoot, "specification/inventories/core-generation-v0.json");

        var cleanRoot = CopySpecificationRoot();
        MutateReference(cleanRoot, reference => reference["source_tree"]!.AsObject()["clean"] = false);
        AssertAnyAssetFailure(cleanRoot, "specification/reference/python-fc53787.json");

        var historicalRevisionRoot = CopySpecificationRoot();
        MutateReference(historicalRevisionRoot, reference => reference["driver"]!.AsObject()["git_revision"] = new string('1', 40));
        AssertAnyAssetFailure(historicalRevisionRoot, "specification/reference/python-fc53787.json");

        var evidenceRoot = CopySpecificationRoot();
        MutateReference(evidenceRoot, reference => reference["packages"] = new JsonArray());
        AssertAnyAssetFailure(evidenceRoot, "specification/reference/python-fc53787.json");
    }

    [Fact]
    public void Release_reader_rejects_empty_reference_and_environment_evidence_after_all_binding_hashes_are_refreshed()
    {
        var packagesRoot = CopySpecificationRoot();
        MutateReference(packagesRoot, reference => reference["packages"] = new JsonObject());
        AssertAnyAssetFailure(packagesRoot, "specification/reference/python-fc53787.json");

        var referenceValidatorRoot = CopySpecificationRoot();
        MutateReference(referenceValidatorRoot, reference => reference["validator"] = new JsonObject());
        AssertAnyAssetFailure(referenceValidatorRoot, "specification/reference/python-fc53787.json");

        AssertEmptyEnvironmentEvidence(static environment => environment["dependency_lock"] = new JsonObject());
        AssertEmptyEnvironmentEvidence(static environment => environment["imports"] = new JsonObject());
        AssertEmptyEnvironmentEvidence(static environment => environment["interpreter"] = new JsonObject());
        AssertEmptyEnvironmentEvidence(static environment => environment["loaded_modules"] = new JsonObject());
        AssertEmptyEnvironmentEvidence(static environment => environment["warning_policy"] = new JsonObject());

        var pairedValidatorRoot = CopySpecificationRoot();
        MutateEnvironmentAndReference(
            pairedValidatorRoot,
            environment => environment["validator"] = new JsonObject(),
            reference => reference["validator"] = new JsonObject());
        AssertAnyAssetFailure(pairedValidatorRoot, "specification/reference/python-fc53787.json");
    }

    [Fact]
    public void Release_reader_keeps_a_selected_alternate_release_name_as_its_diagnostic_context()
    {
        var root = CopySpecificationRoot();
        var alternate = Path.Combine(root, "releases", "portable-proof.json");
        File.Copy(Path.Combine(root, "releases", "core-generation-v0.json"), alternate);

        var assets = ReleaseAssetsReader.ReadAndVerify(root, "releases/portable-proof.json");
        Assert.Equal("releases/portable-proof.json", assets.ReleaseRelativePath);

        MutateJson(alternate, release => release["files"]!.AsObject().Remove("specification/README.md"));
        var failure = Assert.Throws<AssetValidationException>(() =>
            ReleaseAssetsReader.ReadAndVerify(root, "releases/portable-proof.json"));
        Assert.Equal("releases/portable-proof.json", failure.RelativePath);
    }

    [Fact]
    public void Release_reader_root_normalization_preserves_volume_roots_and_returned_assets_own_verified_snapshots()
    {
        var volumeRoot = Path.GetPathRoot(Path.GetFullPath(Directory.GetCurrentDirectory()));
        Assert.NotNull(volumeRoot);
        Assert.Equal(volumeRoot, ReleaseAssetsReader.NormalizeRootPath(volumeRoot!));

        if (OperatingSystem.IsWindows())
        {
            Assert.Throws<ArgumentException>(() => ReleaseAssetsReader.NormalizeRootPath("\\"));
            var driveRelative = volumeRoot![..2] + "relative";
            Assert.Throws<ArgumentException>(() => ReleaseAssetsReader.NormalizeRootPath(driveRelative));
        }

        var root = CopySpecificationRoot();
        var assets = ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json");
        var inventoryFile = Assert.Single(assets.Files, static file => file.RelativePath == "specification/inventories/core-generation-v0.json");
        var referenceFile = Assert.Single(assets.Files, static file => file.RelativePath == "specification/reference/python-fc53787.json");
        var inventoryBytes = inventoryFile.Bytes.ToArray();
        var referenceBytes = referenceFile.Bytes.ToArray();
        var originalCase = assets.Cases[0];
        var originalReference = assets.Reference;

        MutateJson(Path.Combine(root, "inventories", "core-generation-v0.json"), inventory => inventory["profile"] = "mutated-after-read");
        MutateJson(Path.Combine(root, "reference", "python-fc53787.json"), reference => reference["source_tree"]!.AsObject()["clean"] = false);

        Assert.Equal("core-generation", assets.Profile);
        Assert.Equal(originalCase, assets.Cases[0]);
        Assert.Equal(originalReference, assets.Reference);
        Assert.Equal(inventoryBytes, inventoryFile.Bytes.ToArray());
        Assert.Equal(referenceBytes, referenceFile.Bytes.ToArray());
    }

    [Fact]
    public async Task Fixture_reader_uses_verified_raw_inputs_in_inventory_order_and_expected_mutations_do_not_change_adapter_execution()
    {
        var originalRoot = CopySpecificationRoot();
        var originalAssets = ReleaseAssetsReader.ReadAndVerify(originalRoot, "releases/core-generation-v0.json");
        var originalFixtures = FixtureReader.ReadFixtures(originalAssets);
        Assert.Equal(originalAssets.Cases.Where(static item => item.Kind == FixtureKind.Fixture).Select(static item => item.Id), originalFixtures.Select(static item => item.Case.Id));
        Assert.Equal(96, originalFixtures.Count);

        var selected = Assert.Single(originalFixtures, static item => item.Case.Id == "streaming/buffered-equals-streamed");
        var core = Assert.IsType<CoreFixtureInput>(selected.Input);
        Assert.True(core.Request.TryGetValue("messages", out var originalMessages));
        Assert.NotNull(originalMessages);

        var literal = Assert.Single(originalFixtures, static item => item.Case.Id == "validation/literal-reserved-key-objects");
        var literalRequest = Assert.IsType<CoreFixtureInput>(literal.Input).Request;
        var literalSchema = Assert.IsType<AnyInfer.Json.JsonObject>(literalRequest.Properties.Single(static item => item.Name == "schema").Value);
        var literalConst = Assert.IsType<AnyInfer.Json.JsonObject>(literalSchema.Properties.Single(static item => item.Name == "const").Value);
        Assert.Equal("ordinary", Assert.IsType<AnyInfer.Json.JsonString>(literalConst.Properties.Single(static item => item.Name == "$special").Value).Value);
        Assert.Equal("ordinary", Assert.IsType<AnyInfer.Json.JsonString>(literalConst.Properties.Single(static item => item.Name == "$codepoints").Value).Value);

        var mutatedRoot = CopySpecificationRoot();
        var selectedPath = Path.Combine(mutatedRoot, "fixtures", "core-generation", "streaming", "buffered-equals-streamed.json");
        MutateJson(selectedPath, document => document["expected"]!.AsObject()["status"] = "to_be_observed");
        RehashReleaseEntry(mutatedRoot, "specification/fixtures/core-generation/streaming/buffered-equals-streamed.json");
        var mutatedAssets = ReleaseAssetsReader.ReadAndVerify(mutatedRoot, "releases/core-generation-v0.json");
        var mutated = Assert.Single(FixtureReader.ReadFixtures(mutatedAssets), static item => item.Case.Id == "streaming/buffered-equals-streamed");
        var mutatedCore = Assert.IsType<CoreFixtureInput>(mutated.Input);

        Assert.Equal(AnyInfer.Json.JsonWriter.Write(core.Request), AnyInfer.Json.JsonWriter.Write(mutatedCore.Request));
        Assert.Equal(AnyInfer.Json.JsonWriter.Write(core.Route), AnyInfer.Json.JsonWriter.Write(mutatedCore.Route));
        Assert.Equal(AnyInfer.Json.JsonWriter.Write(core.Adapter), AnyInfer.Json.JsonWriter.Write(mutatedCore.Adapter));
        Assert.NotEqual(AnyInfer.Json.JsonWriter.Write(selected.Expected), AnyInfer.Json.JsonWriter.Write(mutated.Expected));

        var originalScript = RequireScript(core.Adapter);
        var mutatedScript = RequireScript(mutatedCore.Adapter);
        var originalEvents = await ReadAdapterEvents(FixtureAdapter.Create(originalScript));
        var mutatedEvents = await ReadAdapterEvents(FixtureAdapter.Create(mutatedScript));
        Assert.Equal(originalEvents, mutatedEvents);
    }

    [Fact]
    public void Fixture_reader_preserves_the_released_clock_envelope_and_rejects_nested_malformed_execution_envelopes()
    {
        var root = CopySpecificationRoot();
        var assets = ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json");
        var clockFixture = Assert.Single(FixtureReader.ReadFixtures(assets), static item => item.Case.Id == "routing/health-recovery-after-ttl");
        var core = Assert.IsType<CoreFixtureInput>(clockFixture.Input);
        var clock = core.Clock;
        Assert.NotNull(clock);
        Assert.True(clock!.TryGetValue("start_ms", out var start));
        Assert.Equal(new BigInteger(59000), Assert.IsType<AnyInfer.Json.JsonInteger>(start).Value);

        AssertNestedFixtureFailure(document => document["clock"] = new JsonObject { ["start_ms"] = "wrong" });
        AssertNestedFixtureFailure(document => document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject()["events"]!.AsArray()[0] = new JsonObject { ["text"] = "x", ["usage"] = new JsonObject() });
        AssertNestedFixtureFailure(document => document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject()["unknown"] = true);
        AssertNestedFixtureFailure(document => document["request"] = "not-an-object");
        AssertNestedFixtureFailure(document =>
        {
            var entry = document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject();
            entry["fail"] = new JsonObject { ["category"] = "auth" };
            entry["fail_in_cleanup"] = new JsonObject { ["category"] = "transport" };
        });
        AssertNestedFixtureFailure(document =>
        {
            var entry = document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject();
            entry["events"]!.AsArray().RemoveAt(2);
            entry["fail_in_cleanup"] = new JsonObject { ["category"] = "transport" };
        });
        AssertNestedFixtureFailure(document => document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject()["fail"] = new JsonObject { ["category"] = "core_only" });
        AssertNestedFixtureFailure(document => document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject()["fail"] = new JsonObject { ["category"] = "auth", ["phase"] = "invalid" });
        AssertNestedFixtureFailure(document => document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject()["events"]!.AsArray()[2]!.AsObject()["final"]!.AsObject()["finish_reason"] = "invalid");
    }

    [Fact]
    public void Fixture_reader_requires_exact_ascii_positive_decimal_stream_cancel_suffixes_without_narrowing_valid_values()
    {
        var validRoot = CopySpecificationRoot();
        MutateStreamCancelFixture(validRoot, document => document["request"]!.AsObject()["consume"] = "stream_cancel_after_events:999999999999999999999999999999999999");
        var validAssets = ReleaseAssetsReader.ReadAndVerify(validRoot, "releases/core-generation-v0.json");
        var valid = Assert.Single(FixtureReader.ReadFixtures(validAssets), static item => item.Case.Id == "streaming/cancel-mid-stream");
        var request = Assert.IsType<CoreFixtureInput>(valid.Input).Request;
        Assert.Equal(
            "stream_cancel_after_events:999999999999999999999999999999999999",
            Assert.IsType<AnyInfer.Json.JsonString>(request.Properties.Single(static property => property.Name == "consume").Value).Value);

        foreach (var suffix in new[] { "0", "abc", "1x", "01", "\u0661" })
        {
            var invalidRoot = CopySpecificationRoot();
            MutateStreamCancelFixture(invalidRoot, document => document["request"]!.AsObject()["consume"] = "stream_cancel_after_events:" + suffix);
            var assets = ReleaseAssetsReader.ReadAndVerify(invalidRoot, "releases/core-generation-v0.json");
            var failure = Assert.Throws<AssetValidationException>(() => FixtureReader.ReadFixtures(assets));
            Assert.Equal("fixture", failure.Category);
            Assert.Equal("specification/fixtures/core-generation/streaming/cancel-mid-stream.json", failure.RelativePath);
        }
    }

    [Fact]
    public async Task Program_verify_rejects_a_self_consistent_but_nested_malformed_fixture_envelope()
    {
        var root = CopySpecificationRoot();
        var fixturePath = Path.Combine(root, "fixtures", "core-generation", "streaming", "buffered-equals-streamed.json");
        MutateJson(fixturePath, document => document["adapter"]!.AsObject()["script"]!.AsArray()[0]!.AsObject()["events"]!.AsArray()[0]!.AsObject()["unknown"] = true);
        RehashReleaseEntry(root, "specification/fixtures/core-generation/streaming/buffered-equals-streamed.json");

        var output = new StringWriter();
        var error = new StringWriter();
        Assert.Equal(2, await Program.RunAsync(["--root", root, "--release", "releases/core-generation-v0.json", "--verify"], output, error));
        Assert.Equal(string.Empty, output.ToString());
        Assert.StartsWith("error fixture specification/fixtures/core-generation/streaming/buffered-equals-streamed.json", error.ToString(), StringComparison.Ordinal);
        Assert.DoesNotContain("Exception", error.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Program_run_async_accepts_help_and_selected_verify_but_refuses_missing_unsafe_and_unproven_report_modes()
    {
        var helpOutput = new StringWriter();
        var helpError = new StringWriter();
        Assert.Equal(0, await Program.RunAsync(["--help"], helpOutput, helpError));
        Assert.Contains("Usage:", helpOutput.ToString(), StringComparison.Ordinal);
        Assert.Equal(string.Empty, helpError.ToString());

        var root = CopySpecificationRoot();
        var output = new StringWriter();
        var error = new StringWriter();
        Assert.Equal(0, await Program.RunAsync(["--root", root, "--release", "releases/core-generation-v0.json", "--verify"], output, error));
        Assert.Contains("verified releases/core-generation-v0.json", output.ToString(), StringComparison.Ordinal);
        Assert.Equal(string.Empty, error.ToString());

        await AssertCliFailure(["--verify"], "arguments");
        await AssertCliFailure(["--root", root, "--release", "../outside.json", "--verify"], "path");
        await AssertCliFailure(["--root", root, "--write-report"], "provenance");
    }

    [Theory]
    [InlineData("\u2028")]
    [InlineData("\u2029")]
    public async Task Program_argument_diagnostics_never_emit_unicode_line_separators_from_release_arguments(string separator)
    {
        var root = CopySpecificationRoot();
        var output = new StringWriter();
        var error = new StringWriter();

        var exitCode = await Program.RunAsync(
            ["--root", root, "--release", "releases/core-generation-v0" + separator + ".json", "--write-report", "--development"],
            output,
            error);

        Assert.Equal(2, exitCode);
        Assert.Equal(string.Empty, output.ToString());
        Assert.Equal("error arguments ." + Environment.NewLine, error.ToString());
    }

    [Fact]
    public async Task Executable_cli_verifies_only_the_explicit_alternate_root()
    {
        var root = CopySpecificationRoot();
        var (exitCode, standardOutput, standardError) = await RunVerifySubprocessAsync(root);
        Assert.Equal(0, exitCode);
        Assert.Contains("verified releases/core-generation-v0.json", standardOutput, StringComparison.Ordinal);
        Assert.Equal(string.Empty, standardError);
    }

    [Fact]
    public async Task Executable_cli_does_not_fall_back_to_the_checkout_when_the_selected_root_is_tampered()
    {
        var root = CopySpecificationRoot();
        File.AppendAllText(Path.Combine(root, "README.md"), "selected-root-tamper\n", new UTF8Encoding(false));

        var (exitCode, standardOutput, standardError) = await RunVerifySubprocessAsync(root);
        Assert.Equal(2, exitCode);
        Assert.Equal(string.Empty, standardOutput);
        Assert.StartsWith("error hash_mismatch specification/README.md", standardError, StringComparison.Ordinal);

        var source = FindSourceSpecificationRoot();
        Assert.NotEqual(root, source);
        _ = ReleaseAssetsReader.ReadAndVerify(source, "releases/core-generation-v0.json");
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

    private string CopySpecificationRoot()
    {
        var source = FindSourceSpecificationRoot();
        var destination = Path.Combine(Path.GetTempPath(), "anyinfer-release-assets-" + Guid.NewGuid().ToString("N"));
        CopyDirectory(source, destination);
        _temporaryRoots.Add(destination);
        return destination;
    }

    private static void CopyDirectory(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source, "*", SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(Path.Combine(destination, Path.GetRelativePath(source, directory)));
        }

        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            File.Copy(file, Path.Combine(destination, Path.GetRelativePath(source, file)));
        }
    }

    private static string FindSourceSpecificationRoot()
    {
        foreach (var start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            for (var current = new DirectoryInfo(start); current is not null; current = current.Parent)
            {
                var candidate = Path.Combine(current.FullName, "specification", "releases", "core-generation-v0.json");
                if (File.Exists(candidate))
                {
                    return Path.GetDirectoryName(Path.GetDirectoryName(candidate))!;
                }
            }
        }

        throw new InvalidOperationException("The source specification tree could not be located for test extraction.");
    }

    private static string FindCsharpRoot()
    {
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            if (File.Exists(Path.Combine(current.FullName, "AnyInfer.sln")))
            {
                return current.FullName;
            }
        }

        throw new InvalidOperationException("The C# solution root could not be located.");
    }

    private static async Task<(int ExitCode, string Output, string Error)> RunVerifySubprocessAsync(string root)
    {
        var csharpRoot = FindCsharpRoot();
        var project = Path.Combine(csharpRoot, "AnyInfer.Conformance", "AnyInfer.Conformance.csproj");
        var start = new ProcessStartInfo("dotnet")
        {
            WorkingDirectory = csharpRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("run");
        start.ArgumentList.Add("--project");
        start.ArgumentList.Add(project);
        start.ArgumentList.Add("--no-build");
        start.ArgumentList.Add("--no-restore");
        start.ArgumentList.Add("--");
        start.ArgumentList.Add("--root");
        start.ArgumentList.Add(root);
        start.ArgumentList.Add("--release");
        start.ArgumentList.Add("releases/core-generation-v0.json");
        start.ArgumentList.Add("--verify");

        using var process = Process.Start(start);
        Assert.NotNull(process);
        var output = await process!.StandardOutput.ReadToEndAsync();
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        return (process.ExitCode, output, error);
    }

    private static void MutateRelease(string root, Action<JsonObject> mutation) =>
        MutateJson(Path.Combine(root, "releases", "core-generation-v0.json"), mutation);

    private static void MutateJson(string path, Action<JsonObject> mutation)
    {
        var document = JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8))!.AsObject();
        mutation(document);
        File.WriteAllText(path, document.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
    }

    private static void RehashReleaseEntry(string root, string sealedPath)
    {
        var relative = sealedPath["specification/".Length..].Replace('/', Path.DirectorySeparatorChar);
        var hash = Sha256(File.ReadAllBytes(Path.Combine(root, relative)));
        MutateRelease(root, release => release["files"]!.AsObject()[sealedPath] = hash);
    }

    private static void MutateInventory(string root, Action<JsonObject> mutation)
    {
        MutateJson(Path.Combine(root, "inventories", "core-generation-v0.json"), mutation);
        RehashReleaseEntry(root, "specification/inventories/core-generation-v0.json");
    }

    private static void MutateInventoryAndReleaseCase(
        string root,
        string caseId,
        Action<JsonObject, JsonObject> mutation)
    {
        var inventoryPath = Path.Combine(root, "inventories", "core-generation-v0.json");
        var releasePath = Path.Combine(root, "releases", "core-generation-v0.json");
        var inventory = JsonNode.Parse(File.ReadAllText(inventoryPath, Encoding.UTF8))!.AsObject();
        var release = JsonNode.Parse(File.ReadAllText(releasePath, Encoding.UTF8))!.AsObject();
        var inventoryCase = inventory["cases"]!.AsArray()
            .Select(static item => item!.AsObject())
            .Single(item => string.Equals(item["id"]!.GetValue<string>(), caseId, StringComparison.Ordinal));
        var releaseCase = release["case_inventory"]!.AsArray()
            .Select(static item => item!.AsObject())
            .Single(item => string.Equals(item["id"]!.GetValue<string>(), caseId, StringComparison.Ordinal));

        mutation(inventoryCase, releaseCase);
        File.WriteAllText(inventoryPath, inventory.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
        File.WriteAllText(releasePath, release.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
        RehashReleaseEntry(root, "specification/inventories/core-generation-v0.json");
    }

    private static void MutateReference(string root, Action<JsonObject> mutation)
    {
        var relative = "specification/reference/python-fc53787.json";
        MutateJson(Path.Combine(root, "reference", "python-fc53787.json"), mutation);
        RehashReleaseEntry(root, relative);
    }

    private void AssertEmptyEnvironmentEvidence(Action<JsonObject> environmentMutation)
    {
        var root = CopySpecificationRoot();
        MutateEnvironmentAndReference(root, environmentMutation, static _ => { });
        AssertAnyAssetFailure(root, "specification/reference/python-fc53787.environment.json");
    }

    private static void MutateEnvironmentAndReference(
        string root,
        Action<JsonObject> environmentMutation,
        Action<JsonObject> referenceMutation)
    {
        const string environmentSealedPath = "specification/reference/python-fc53787.environment.json";
        const string referenceSealedPath = "specification/reference/python-fc53787.json";
        var environmentPath = Path.Combine(root, "reference", "python-fc53787.environment.json");
        var referencePath = Path.Combine(root, "reference", "python-fc53787.json");
        var environment = JsonNode.Parse(File.ReadAllText(environmentPath, Encoding.UTF8))!.AsObject();
        var reference = JsonNode.Parse(File.ReadAllText(referencePath, Encoding.UTF8))!.AsObject();

        environmentMutation(environment);
        File.WriteAllText(environmentPath, environment.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
        referenceMutation(reference);
        reference["environment"]!.AsObject()["sha256"] = Sha256(File.ReadAllBytes(environmentPath));
        File.WriteAllText(referencePath, reference.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
        RehashReleaseEntry(root, environmentSealedPath);
        RehashReleaseEntry(root, referenceSealedPath);
    }

    private void AssertNestedFixtureFailure(Action<JsonObject> mutation)
    {
        var root = CopySpecificationRoot();
        var fixturePath = Path.Combine(root, "fixtures", "core-generation", "streaming", "buffered-equals-streamed.json");
        MutateJson(fixturePath, mutation);
        RehashReleaseEntry(root, "specification/fixtures/core-generation/streaming/buffered-equals-streamed.json");
        var assets = ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json");
        var failure = Assert.Throws<AssetValidationException>(() => FixtureReader.ReadFixtures(assets));
        Assert.Equal("fixture", failure.Category);
        Assert.Equal("specification/fixtures/core-generation/streaming/buffered-equals-streamed.json", failure.RelativePath);
    }

    private void MutateStreamCancelFixture(string root, Action<JsonObject> mutation)
    {
        const string sealedPath = "specification/fixtures/core-generation/streaming/cancel-mid-stream.json";
        MutateJson(Path.Combine(root, "fixtures", "core-generation", "streaming", "cancel-mid-stream.json"), mutation);
        RehashReleaseEntry(root, sealedPath);
    }

    private static string Sha256(ReadOnlySpan<byte> bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static AnyInfer.Json.JsonArray RequireScript(AnyInfer.Json.JsonObject adapter)
    {
        Assert.True(adapter.TryGetValue("script", out var script));
        return Assert.IsType<AnyInfer.Json.JsonArray>(script);
    }

    private static async Task<IReadOnlyList<string>> ReadAdapterEvents(FixtureAdapter adapter)
    {
        var events = new List<string>();
        await using (adapter)
        {
            await foreach (var item in adapter.GenerateAsync(new AnyInfer.Providers.WireRequest(
                "alpha",
                [new AnyInfer.Message("user", [new AnyInfer.Text("fixture input")])],
                new AnyInfer.Sampling())))
            {
                events.Add(item switch
                {
                    AnyInfer.Providers.AdapterTextDelta delta => "text:" + delta.Text,
                    AnyInfer.Providers.AdapterUsage usage => "usage:" + usage.Usage.InputTokens + ":" + usage.Usage.OutputTokens,
                    AnyInfer.Providers.AdapterFinal final => "final:" + final.FinishReason,
                    _ => throw new InvalidOperationException("Unexpected fixture event."),
                });
            }
        }

        return events;
    }

    private static void AssertAssetFailure(string root, string category, string relativePath)
    {
        var failure = Assert.Throws<AssetValidationException>(() => ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json"));
        Assert.Equal(category, failure.Category);
        Assert.Equal(relativePath, failure.RelativePath);
    }

    private static void AssertAnyAssetFailure(string root, string relativePath)
    {
        var failure = Assert.Throws<AssetValidationException>(() =>
            ReleaseAssetsReader.ReadAndVerify(root, "releases/core-generation-v0.json"));
        Assert.False(string.IsNullOrWhiteSpace(failure.Category));
        Assert.Equal(relativePath, failure.RelativePath);
    }

    private static async Task AssertCliFailure(string[] args, string category)
    {
        var output = new StringWriter();
        var error = new StringWriter();
        Assert.Equal(2, await Program.RunAsync(args, output, error));
        Assert.Equal(string.Empty, output.ToString());
        Assert.StartsWith("error " + category + " ", error.ToString(), StringComparison.Ordinal);
        Assert.DoesNotContain("Exception", error.ToString(), StringComparison.Ordinal);
    }
}
