using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using AnyInfer.Json;

namespace AnyInfer.Conformance;

internal enum FixtureKind
{
    Fixture,
    DriverAssertion,
}

internal sealed record ReleaseFile(string RelativePath, string Sha256, string FullPath, ReadOnlyMemory<byte> Bytes);

internal sealed record InventoryCase(
    string Id,
    FixtureKind Kind,
    string? RelativePath,
    string Family,
    JsonValue? Extension,
    string? RecipeRef);

internal sealed record ReferenceBinding(
    string ManifestRelativePath,
    string EnvironmentRelativePath,
    string EnvironmentSha256,
    string ReferenceRunRevision,
    string DriverRelativePath,
    string DriverRevision);

internal sealed class ReleaseAssets
{
    public ReleaseAssets(
        string rootPath,
        string releaseRelativePath,
        string releaseSha256,
        string releaseId,
        string profile,
        string profileRevision,
        IEnumerable<ReleaseFile> files,
        IEnumerable<InventoryCase> cases,
        ReferenceBinding reference)
    {
        RootPath = rootPath;
        ReleaseRelativePath = releaseRelativePath;
        ReleaseSha256 = releaseSha256;
        ReleaseId = releaseId;
        Profile = profile;
        ProfileRevision = profileRevision;
        Files = Array.AsReadOnly(files.ToArray());
        Cases = Array.AsReadOnly(cases.ToArray());
        Reference = reference;
    }

    public string RootPath { get; }
    public string ReleaseRelativePath { get; }
    public string ReleaseSha256 { get; }
    public string ReleaseId { get; }
    public string Profile { get; }
    public string ProfileRevision { get; }
    public IReadOnlyList<ReleaseFile> Files { get; }
    public IReadOnlyList<InventoryCase> Cases { get; }
    public ReferenceBinding Reference { get; }
}

internal sealed class AssetValidationException : Exception
{
    public AssetValidationException(string category, string relativePath, string message)
        : base(message)
    {
        Category = category;
        RelativePath = relativePath;
    }

    public string Category { get; }
    public string RelativePath { get; }
}

internal static class ReleaseAssetsReader
{
    private const string SpecificationPrefix = "specification/";
    private const string InventoryPath = "specification/inventories/core-generation-v0.json";
    private static readonly string[] NormativePaths =
    [
        "specification/README.md",
        "specification/core-generation.md",
        "specification/MAINTENANCE.md",
    ];
    private static readonly string[] SchemaPaths =
    [
        "specification/schemas/fixture-v0.schema.json",
        "specification/schemas/inventory-v0.schema.json",
        "specification/schemas/report-v0.schema.json",
        "specification/schemas/transport-v0.schema.json",
    ];

    private static readonly string[] AllowedExtensions =
    [
        "schema.ref",
        "schema.combinators",
        "schema.other_dialects",
        "schema.boolean_subschema",
        "schema.unknown_keywords_ignored",
        "messages.tool_role",
        "targets.alias",
        "messages.non_text_parts",
    ];
    public static ReleaseAssets ReadAndVerify(string absoluteRoot, string relativeReleasePath)
    {
        var root = ValidateRoot(absoluteRoot);
        var releasePath = ResolveRelative(root, relativeReleasePath, "release_path");
        var releaseBytes = ReadBytes(releasePath, relativeReleasePath);
        var release = ReadObject(releaseBytes, relativeReleasePath, "release_json");
        RequireExactKeys(release, relativeReleasePath,
        ["release", "profile", "profile_revision", "created_at", "reference_manifest", "files", "case_inventory"]);

        var releaseId = RequireString(release, "release", relativeReleasePath);
        var profile = RequireString(release, "profile", relativeReleasePath);
        var profileRevision = RequireString(release, "profile_revision", relativeReleasePath);
        if (!string.Equals(releaseId, "core-generation-v0", StringComparison.Ordinal) ||
            !string.Equals(profile, "core-generation", StringComparison.Ordinal) ||
            !string.Equals(profileRevision, "v0", StringComparison.Ordinal) ||
            string.IsNullOrWhiteSpace(RequireString(release, "created_at", relativeReleasePath)))
        {
            throw Invalid("release_metadata", relativeReleasePath);
        }
        var referenceManifestPath = RequireSealedPath(RequireString(release, "reference_manifest", relativeReleasePath), relativeReleasePath);
        var releaseFiles = RequireObject(release, "files", relativeReleasePath);
        var releaseCases = RequireArray(release, "case_inventory", relativeReleasePath);
        var snapshots = new Dictionary<string, byte[]>(StringComparer.Ordinal);

        var inventory = ReadObject(
            ReadVerifiedSnapshot(root, InventoryPath, releaseFiles, relativeReleasePath, snapshots),
            InventoryPath,
            "inventory_json");
        RequireExactKeys(inventory, InventoryPath, ["profile", "profile_revision", "requirements", "cases"]);
        if (!string.Equals(profile, RequireString(inventory, "profile", InventoryPath), StringComparison.Ordinal) ||
            !string.Equals(profileRevision, RequireString(inventory, "profile_revision", InventoryPath), StringComparison.Ordinal))
        {
            throw Invalid("inventory_mismatch", InventoryPath);
        }

        var requirements = RequireArray(inventory, "requirements", InventoryPath);
        var inventoryCases = ParseInventoryCases(RequireArray(inventory, "cases", InventoryPath));
        ValidateRequirements(requirements, inventoryCases);
        var releaseInventoryCases = ParseReleaseCases(releaseCases, relativeReleasePath);
        VerifyCaseInventory(inventoryCases, releaseInventoryCases, relativeReleasePath);

        var reference = ParseReference(root, referenceManifestPath, releaseFiles, relativeReleasePath, snapshots);
        var expectedPaths = BuildExpectedPaths(inventoryCases, referenceManifestPath, reference.EnvironmentRelativePath);
        VerifyFileSetAndHashes(root, releaseFiles, expectedPaths, relativeReleasePath);

        var files = expectedPaths.Select(path =>
        {
            var hash = RequireString(releaseFiles, path, relativeReleasePath);
            var fullPath = ResolveSealedPath(root, path);
            var bytes = ReadVerifiedSnapshot(root, path, releaseFiles, relativeReleasePath, snapshots);
            return new ReleaseFile(path, hash, fullPath, bytes);
        }).ToArray();

        return new ReleaseAssets(
            root,
            relativeReleasePath,
            Sha256(releaseBytes),
            releaseId,
            profile,
            profileRevision,
            files,
            inventoryCases,
            reference);
    }

    private static string ValidateRoot(string absoluteRoot)
    {
        if (string.IsNullOrWhiteSpace(absoluteRoot) || !Path.IsPathFullyQualified(absoluteRoot))
        {
            throw Invalid("root", ".");
        }

        var root = NormalizeRootPath(absoluteRoot);
        if (!Directory.Exists(root))
        {
            throw Invalid("root", ".");
        }

        RejectReparsePoint(root, ".");
        return root;
    }

    internal static string NormalizeRootPath(string absoluteRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absoluteRoot);
        if (!Path.IsPathFullyQualified(absoluteRoot))
        {
            throw new ArgumentException("A fully qualified path is required.", nameof(absoluteRoot));
        }

        return Path.TrimEndingDirectorySeparator(Path.GetFullPath(absoluteRoot));
    }
    private static IReadOnlyList<InventoryCase> ParseInventoryCases(JsonArray cases)
    {
        var parsed = new List<InventoryCase>();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var value in cases.Items)
        {
            if (value is not JsonObject item)
            {
                throw Invalid("inventory_case", InventoryPath);
            }

            var kind = RequireString(item, "kind", InventoryPath) switch
            {
                "fixture" => FixtureKind.Fixture,
                "driver_assertion" => FixtureKind.DriverAssertion,
                _ => throw Invalid("inventory_kind", InventoryPath),
            };
            RequireExactKeys(item, InventoryPath, kind == FixtureKind.Fixture
                ? ["id", "kind", "path", "family", "extension"]
                : ["id", "kind", "path", "family", "extension", "recipe_ref"]);

            var id = RequireCaseId(RequireString(item, "id", InventoryPath), InventoryPath);
            if (!ids.Add(id))
            {
                throw Invalid("duplicate_case", InventoryPath);
            }

            var path = RequireNullableString(item, "path", InventoryPath);
            var family = RequireNonEmptyString(item, "family", InventoryPath);
            var extension = RequireExtension(item, "extension", InventoryPath);
            var recipe = kind == FixtureKind.DriverAssertion
                ? RequireNonEmptyString(item, "recipe_ref", InventoryPath)
                : null;
            if ((kind == FixtureKind.Fixture) != (path is not null) ||
                (kind == FixtureKind.DriverAssertion && (extension is not null || !string.Equals(family, "driver", StringComparison.Ordinal) || !string.Equals(recipe, id, StringComparison.Ordinal))) ||
                (kind == FixtureKind.Fixture && path is not null && !path.StartsWith("specification/fixtures/", StringComparison.Ordinal)))
            {
                throw Invalid("inventory_case", InventoryPath);
            }

            parsed.Add(new InventoryCase(
                id,
                kind,
                path is null ? null : RequireSealedPath(path, InventoryPath),
                family,
                extension,
                recipe));
        }

        return Array.AsReadOnly(parsed.ToArray());
    }
    private static IReadOnlyList<InventoryCase> ParseReleaseCases(JsonArray cases, string relativeReleasePath)
    {
        var parsed = new List<InventoryCase>();
        foreach (var value in cases.Items)
        {
            if (value is not JsonObject item)
            {
                throw Invalid("release_case", relativeReleasePath);
            }

            var kind = RequireString(item, "kind", relativeReleasePath) switch
            {
                "fixture" => FixtureKind.Fixture,
                "driver_assertion" => FixtureKind.DriverAssertion,
                _ => throw Invalid("release_case", relativeReleasePath),
            };
            RequireExactKeys(item, relativeReleasePath, kind == FixtureKind.Fixture
                ? ["id", "kind", "path", "family", "extension"]
                : ["id", "kind", "path", "family", "extension", "recipe_ref"]);
            parsed.Add(new InventoryCase(
                RequireCaseId(RequireString(item, "id", relativeReleasePath), relativeReleasePath),
                kind,
                RequireNullableString(item, "path", relativeReleasePath),
                RequireString(item, "family", relativeReleasePath),
                RequireExtension(item, "extension", relativeReleasePath),
                kind == FixtureKind.DriverAssertion ? RequireString(item, "recipe_ref", relativeReleasePath) : null));
        }

        return parsed;
    }

    private static void VerifyCaseInventory(IReadOnlyList<InventoryCase> inventory, IReadOnlyList<InventoryCase> release, string relativeReleasePath)
    {
        if (inventory.Count != release.Count)
        {
            throw Invalid("case_inventory", relativeReleasePath);
        }

        for (var index = 0; index < inventory.Count; index++)
        {
            var expected = inventory[index];
            var actual = release[index];
            if (!string.Equals(expected.Id, actual.Id, StringComparison.Ordinal) ||
                expected.Kind != actual.Kind ||
                !string.Equals(expected.RelativePath, actual.RelativePath, StringComparison.Ordinal) ||
                !string.Equals(expected.Family, actual.Family, StringComparison.Ordinal) ||
                !string.Equals(expected.RecipeRef, actual.RecipeRef, StringComparison.Ordinal) ||
                !JsonEquals(expected.Extension, actual.Extension))
            {
                throw Invalid("case_inventory", relativeReleasePath);
            }
        }
    }

    private static ReferenceBinding ParseReference(
        string root,
        string referenceManifestPath,
        JsonObject releaseFiles,
        string releasePath,
        IDictionary<string, byte[]> snapshots)
    {
        var reference = ReadObject(
            ReadVerifiedSnapshot(root, referenceManifestPath, releaseFiles, releasePath, snapshots),
            referenceManifestPath,
            "reference_json");
        RequireExactKeys(reference, referenceManifestPath,
        ["driver", "environment", "implementation", "interpreter", "packages", "produced_at", "reference_run_revision", "source_tree", "validator", "warning_policy"]);
        if (!string.Equals(RequireString(reference, "implementation", referenceManifestPath), "anyinfer-python", StringComparison.Ordinal) ||
            string.IsNullOrWhiteSpace(RequireString(reference, "interpreter", referenceManifestPath)) ||
            string.IsNullOrWhiteSpace(RequireString(reference, "produced_at", referenceManifestPath)) ||
            !string.Equals(RequireString(reference, "warning_policy", referenceManifestPath), "error", StringComparison.Ordinal))
        {
            throw Invalid("reference_binding", referenceManifestPath);
        }

        ValidatePackageVersions(RequireObject(reference, "packages", referenceManifestPath), referenceManifestPath);
        ValidateValidatorEvidence(RequireObject(reference, "validator", referenceManifestPath), referenceManifestPath);
        var sourceTree = RequireObject(reference, "source_tree", referenceManifestPath);
        RequireExactKeys(sourceTree, referenceManifestPath, ["clean"]);
        if (Require(sourceTree, "clean", referenceManifestPath) is not JsonBoolean { Value: true })
        {
            throw Invalid("reference_binding", referenceManifestPath);
        }

        var driver = RequireObject(reference, "driver", referenceManifestPath);
        RequireExactKeys(driver, referenceManifestPath, ["git_revision", "path"]);
        var environmentDescriptor = RequireObject(reference, "environment", referenceManifestPath);
        RequireExactKeys(environmentDescriptor, referenceManifestPath, ["path", "sha256"]);
        var environmentPath = RequireSealedPath(RequireString(environmentDescriptor, "path", referenceManifestPath), referenceManifestPath);
        var environmentHash = RequireHash(RequireString(environmentDescriptor, "sha256", referenceManifestPath), referenceManifestPath);
        var bytes = ReadVerifiedSnapshot(root, environmentPath, releaseFiles, releasePath, snapshots);
        if (!string.Equals(environmentHash, Sha256(bytes), StringComparison.Ordinal))
        {
            throw Invalid("environment_hash", environmentPath);
        }

        var environmentDocument = ReadObject(bytes, environmentPath, "environment_json");
        var environmentRevision = ValidateEnvironment(environmentDocument, environmentPath);
        var referenceRevision = RequireRevision(RequireString(reference, "reference_run_revision", referenceManifestPath), referenceManifestPath);
        var driverPath = RequireSafeRepositoryRelative(RequireNonEmptyString(driver, "path", referenceManifestPath), referenceManifestPath);
        var driverRevision = RequireRevision(RequireString(driver, "git_revision", referenceManifestPath), referenceManifestPath);
        if (!string.Equals(environmentRevision, referenceRevision, StringComparison.Ordinal) ||
            !string.Equals(driverRevision, referenceRevision, StringComparison.Ordinal))
        {
            throw Invalid("reference_binding", referenceManifestPath);
        }

        return new ReferenceBinding(
            referenceManifestPath,
            environmentPath,
            environmentHash,
            referenceRevision,
            driverPath,
            driverRevision);
    }
    private static void ValidateRequirements(JsonArray requirements, IReadOnlyList<InventoryCase> cases)
    {
        var known = new HashSet<string>(cases.Select(static item => item.Id), StringComparer.Ordinal);
        var requirementsSeen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var value in requirements.Items)
        {
            if (value is not JsonObject requirement)
            {
                throw Invalid("requirement", InventoryPath);
            }

            RequireExactKeys(requirement, InventoryPath, ["id", "spec_ref", "case_ids"]);
            var requirementId = RequireNonEmptyString(requirement, "id", InventoryPath);
            if (!requirementsSeen.Add(requirementId) || string.IsNullOrWhiteSpace(RequireNonEmptyString(requirement, "spec_ref", InventoryPath)))
            {
                throw Invalid("requirement", InventoryPath);
            }

            var caseIds = RequireArray(requirement, "case_ids", InventoryPath);
            if (caseIds.Items.Count == 0)
            {
                throw Invalid("requirement", InventoryPath);
            }

            foreach (var caseId in caseIds.Items)
            {
                if (caseId is not JsonString text || !known.Contains(text.Value))
                {
                    throw Invalid("requirement", InventoryPath);
                }
            }
        }
    }

    private static string ValidateEnvironment(JsonObject environment, string path)
    {
        RequireExactKeys(environment, path,
        ["dependency_lock", "environment_version", "imports", "interpreter", "loaded_modules", "reference_run_revision", "validator", "warning_policy"]);
        if (string.IsNullOrWhiteSpace(RequireString(environment, "environment_version", path)))
        {
            throw Invalid("environment_json", path);
        }

        ValidateDependencyLock(RequireObject(environment, "dependency_lock", path), path);
        ValidatePathHashMap(RequireObject(environment, "imports", path), path);
        ValidateInterpreter(RequireObject(environment, "interpreter", path), path);
        ValidatePathHashMap(RequireObject(environment, "loaded_modules", path), path);
        ValidateValidatorEvidence(RequireObject(environment, "validator", path), path);
        ValidateWarningPolicy(RequireObject(environment, "warning_policy", path), path);
        return RequireRevision(RequireString(environment, "reference_run_revision", path), path);
    }

    private static void ValidatePackageVersions(JsonObject packages, string path)
    {
        RequireNonEmptyObject(packages, path, "reference_binding");
        foreach (var property in packages.Properties)
        {
            if (string.IsNullOrWhiteSpace(property.Name) || property.Value is not JsonString { Value.Length: > 0 })
            {
                throw Invalid("reference_binding", path);
            }
        }
    }

    private static void ValidateValidatorEvidence(JsonObject validator, string path)
    {
        RequireExactKeys(validator, path, ["defaults", "resource_identities", "selected"]);
        var defaults = RequireObject(validator, "defaults", path);
        RequireNonEmptyObject(defaults, path, "reference_binding");
        foreach (var property in defaults.Properties)
        {
            if (property.Value is not JsonString { Value.Length: > 0 })
            {
                throw Invalid("reference_binding", path);
            }
        }

        if (string.IsNullOrWhiteSpace(RequireString(validator, "selected", path)))
        {
            throw Invalid("reference_binding", path);
        }

        var identities = RequireArray(validator, "resource_identities", path);
        if (identities.Items.Count == 0)
        {
            throw Invalid("reference_binding", path);
        }

        foreach (var value in identities.Items)
        {
            if (value is not JsonObject identity)
            {
                throw Invalid("reference_binding", path);
            }

            RequireExactKeys(identity, path, ["sha256", "uri"]);
            _ = RequireHash(Require(identity, "sha256", path), path);
            if (string.IsNullOrWhiteSpace(RequireString(identity, "uri", path)))
            {
                throw Invalid("reference_binding", path);
            }
        }
    }

    private static void ValidateDependencyLock(JsonObject dependencyLock, string path)
    {
        RequireNonEmptyObject(dependencyLock, path, "environment_json");
        foreach (var property in dependencyLock.Properties)
        {
            if (property.Value is not JsonObject package)
            {
                throw Invalid("environment_json", path);
            }

            RequireExactKeys(package, path, ["direct_url_sha256", "metadata_sha256", "record_sha256", "requires", "version"]);
            var directUrlHash = Require(package, "direct_url_sha256", path);
            if (directUrlHash is not JsonNull and not JsonString)
            {
                throw Invalid("environment_json", path);
            }

            if (directUrlHash is JsonString)
            {
                _ = RequireHash(directUrlHash, path);
            }

            _ = RequireHash(Require(package, "metadata_sha256", path), path);
            _ = RequireHash(Require(package, "record_sha256", path), path);
            if (string.IsNullOrWhiteSpace(RequireString(package, "version", path)))
            {
                throw Invalid("environment_json", path);
            }

            RequireStringArray(RequireArray(package, "requires", path), path, "environment_json");
        }
    }

    private static void ValidatePathHashMap(JsonObject map, string path)
    {
        RequireNonEmptyObject(map, path, "environment_json");
        foreach (var property in map.Properties)
        {
            if (property.Value is not JsonObject entry)
            {
                throw Invalid("environment_json", path);
            }

            RequireExactKeys(entry, path, ["path", "sha256"]);
            if (string.IsNullOrWhiteSpace(RequireString(entry, "path", path)))
            {
                throw Invalid("environment_json", path);
            }

            _ = RequireHash(Require(entry, "sha256", path), path);
        }
    }

    private static void ValidateInterpreter(JsonObject interpreter, string path)
    {
        RequireExactKeys(interpreter, path, ["executable", "executable_sha256", "implementation", "version"]);
        foreach (var name in new[] { "executable", "implementation", "version" })
        {
            if (string.IsNullOrWhiteSpace(RequireString(interpreter, name, path)))
            {
                throw Invalid("environment_json", path);
            }
        }

        _ = RequireHash(Require(interpreter, "executable_sha256", path), path);
    }

    private static void ValidateWarningPolicy(JsonObject warningPolicy, string path)
    {
        RequireExactKeys(warningPolicy, path, ["filters", "mode"]);
        if (!string.Equals(RequireString(warningPolicy, "mode", path), "error", StringComparison.Ordinal))
        {
            throw Invalid("environment_json", path);
        }

        var filters = RequireArray(warningPolicy, "filters", path);
        foreach (var value in filters.Items)
        {
            if (value is not JsonObject filter)
            {
                throw Invalid("environment_json", path);
            }

            RequireExactKeys(filter, path, ["action", "category", "lineno", "message", "module"]);
            if (string.IsNullOrWhiteSpace(RequireString(filter, "action", path)) ||
                string.IsNullOrWhiteSpace(RequireString(filter, "category", path)) ||
                Require(filter, "lineno", path) is not JsonInteger)
            {
                throw Invalid("environment_json", path);
            }

            if (Require(filter, "message", path) is not JsonNull and not JsonString ||
                Require(filter, "module", path) is not JsonNull and not JsonString)
            {
                throw Invalid("environment_json", path);
            }
        }
    }

    private static void RequireStringArray(JsonArray values, string path, string category)
    {
        foreach (var value in values.Items)
        {
            if (value is not JsonString)
            {
                throw Invalid(category, path);
            }
        }
    }

    private static void RequireNonEmptyObject(JsonObject value, string path, string category)
    {
        if (value.Properties.Count == 0)
        {
            throw Invalid(category, path);
        }
    }
    private static JsonValue? RequireExtension(JsonObject value, string name, string path)
    {
        var extension = RequireLiteralOrNull(value, name, path);
        if (extension is null)
        {
            return null;
        }

        if (extension is not JsonString text || !AllowedExtensions.Contains(text.Value, StringComparer.Ordinal))
        {
            throw Invalid("extension", path);
        }

        return extension;
    }

    private static string RequireCaseId(string value, string path)
    {
        var segments = value.Split('/', StringSplitOptions.None);
        if (segments.Length < 2 || segments.Any(static segment => string.IsNullOrEmpty(segment)) ||
            !IsFirstIdSegment(segments[0]) || segments.Skip(1).Any(static segment => !IsLaterIdSegment(segment)))
        {
            throw Invalid("case_id", path);
        }

        return value;
    }

    private static bool IsFirstIdSegment(string segment) =>
        segment[0] is >= 'a' and <= 'z' && segment.All(static character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '-');

    private static bool IsLaterIdSegment(string segment) =>
        (segment[0] is >= 'a' and <= 'z' or >= '0' and <= '9') &&
        segment.All(static character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '-');

    private static string RequireSafeRepositoryRelative(string value, string path)
    {
        var normalized = value.TrimEnd('/');
        if (string.IsNullOrWhiteSpace(normalized) || Path.IsPathFullyQualified(value) || value.Contains('\\') ||
            normalized.Split('/', StringSplitOptions.None).Any(static segment => string.IsNullOrEmpty(segment) || segment is "." or ".."))
        {
            throw Invalid("reference_binding", path);
        }

        return value;
    }
    private static string RequireNonEmptyString(JsonObject value, string name, string path)
    {
        var result = RequireString(value, name, path);
        return string.IsNullOrEmpty(result) ? throw Invalid("shape", path) : result;
    }
    private static IReadOnlyList<string> BuildExpectedPaths(IReadOnlyList<InventoryCase> cases, string referenceManifest, string environment)
    {
        var paths = new HashSet<string>(NormativePaths, StringComparer.Ordinal);
        paths.UnionWith(SchemaPaths);
        paths.Add(InventoryPath);
        paths.Add(referenceManifest);
        paths.Add(environment);
        foreach (var item in cases)
        {
            if (item.RelativePath is not null)
            {
                paths.Add(item.RelativePath);
            }
        }

        return paths.OrderBy(static path => path, StringComparer.Ordinal).ToArray();
    }

    private static void VerifyFileSetAndHashes(string root, JsonObject releaseFiles, IReadOnlyList<string> expectedPaths, string releasePath)
    {
        if (releaseFiles.Properties.Count != expectedPaths.Count)
        {
            throw Invalid("release_files", releasePath);
        }

        var previous = string.Empty;
        foreach (var property in releaseFiles.Properties)
        {
            var path = RequireSealedPath(property.Name, releasePath);
            if (string.CompareOrdinal(previous, path) >= 0 || !expectedPaths.Contains(path, StringComparer.Ordinal))
            {
                throw Invalid("release_files", releasePath);
            }

            previous = path;
            _ = RequireHash(property.Value, releasePath);
            _ = ResolveSealedPath(root, path);
        }
    }

    private static string ResolveSealedPath(string root, string sealedPath)
    {
        var normalized = RequireSealedPath(sealedPath, sealedPath);
        var relative = normalized[SpecificationPrefix.Length..];
        return ResolveRelative(root, relative, normalized);
    }

    private static string ResolveRelative(string root, string relativePath, string diagnosticPath)
    {
        if (string.IsNullOrWhiteSpace(relativePath) || Path.IsPathFullyQualified(relativePath) || relativePath.Contains('\\') || relativePath.Contains(':'))
        {
            throw Invalid("path", diagnosticPath);
        }

        var segments = relativePath.Split('/', StringSplitOptions.None);
        if (segments.Any(static segment => string.IsNullOrEmpty(segment) || segment is "." or ".."))
        {
            throw Invalid("path", diagnosticPath);
        }

        var current = root;
        foreach (var segment in segments)
        {
            var entries = Directory.EnumerateFileSystemEntries(current)
                .Select(Path.GetFileName)
                .Where(static name => name is not null)
                .ToArray();
            if (!entries.Contains(segment, StringComparer.Ordinal))
            {
                throw Invalid(entries.Contains(segment, StringComparer.OrdinalIgnoreCase) ? "path_alias" : "missing", diagnosticPath);
            }

            current = Path.Combine(current, segment);
            RejectReparsePoint(current, diagnosticPath);
        }

        var full = Path.GetFullPath(current);
        var expected = Path.GetFullPath(Path.Combine(root, Path.Combine(segments)));
        if (!string.Equals(full, expected, StringComparison.OrdinalIgnoreCase))
        {
            throw Invalid("path", diagnosticPath);
        }

        return full;
    }

    private static string RequireSealedPath(string value, string diagnosticPath)
    {
        if (!value.StartsWith(SpecificationPrefix, StringComparison.Ordinal) || value.Length == SpecificationPrefix.Length)
        {
            throw Invalid("path", diagnosticPath);
        }

        var suffix = value[SpecificationPrefix.Length..];
        if (value.Contains('\\') || suffix.Split('/').Any(static segment => string.IsNullOrEmpty(segment) || segment is "." or ".."))
        {
            throw Invalid("path", diagnosticPath);
        }

        return value;
    }

    private static void RejectReparsePoint(string path, string diagnosticPath)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw Invalid("reparse_point", diagnosticPath);
        }
    }

    private static byte[] ReadVerifiedSnapshot(
        string root,
        string sealedPath,
        JsonObject releaseFiles,
        string releasePath,
        IDictionary<string, byte[]> snapshots)
    {
        if (snapshots.TryGetValue(sealedPath, out var existing))
        {
            return existing;
        }

        var expectedHash = RequireHash(Require(releaseFiles, sealedPath, releasePath), releasePath);
        var bytes = ReadBytes(ResolveSealedPath(root, sealedPath), sealedPath);
        if (!string.Equals(expectedHash, Sha256(bytes), StringComparison.Ordinal))
        {
            throw Invalid("hash_mismatch", sealedPath);
        }

        snapshots.Add(sealedPath, bytes);
        return bytes;
    }
    private static byte[] ReadBytes(string fullPath, string diagnosticPath)
    {
        try
        {
            return File.ReadAllBytes(fullPath);
        }
        catch (IOException)
        {
            throw Invalid("read", diagnosticPath);
        }
        catch (UnauthorizedAccessException)
        {
            throw Invalid("read", diagnosticPath);
        }
    }

    private static JsonObject ReadObject(ReadOnlySpan<byte> bytes, string path, string category)
    {
        try
        {
            EnsureUniqueObjectKeys(bytes);
            return JsonReader.Read(bytes) as JsonObject ?? throw Invalid(category, path);
        }
        catch (FormatException)
        {
            throw Invalid(category, path);
        }
        catch (JsonException)
        {
            throw Invalid(category, path);
        }
    }

    private static void EnsureUniqueObjectKeys(ReadOnlySpan<byte> bytes)
    {
        var reader = new Utf8JsonReader(bytes);
        var objectKeys = new Stack<HashSet<string>>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.StartObject)
            {
                objectKeys.Push(new HashSet<string>(StringComparer.Ordinal));
            }
            else if (reader.TokenType == JsonTokenType.EndObject)
            {
                objectKeys.Pop();
            }
            else if (reader.TokenType == JsonTokenType.PropertyName)
            {
                var name = reader.GetString() ?? throw new FormatException("JSON property name is null.");
                if (!objectKeys.Peek().Add(name))
                {
                    throw new FormatException("JSON object contains a duplicate property name.");
                }
            }
        }
    }

    private static JsonObject RequireObject(JsonObject value, string name, string path)
    {
        return Require(value, name, path) as JsonObject ?? throw Invalid("shape", path);
    }

    private static JsonArray RequireArray(JsonObject value, string name, string path)
    {
        return Require(value, name, path) as JsonArray ?? throw Invalid("shape", path);
    }

    private static string RequireString(JsonObject value, string name, string path)
    {
        return Require(value, name, path) is JsonString text ? text.Value : throw Invalid("shape", path);
    }

    private static string? RequireNullableString(JsonObject value, string name, string path)
    {
        return Require(value, name, path) switch
        {
            JsonNull => null,
            JsonString text => text.Value,
            _ => throw Invalid("shape", path),
        };
    }

    private static JsonValue? RequireLiteralOrNull(JsonObject value, string name, string path)
    {
        var literal = Require(value, name, path);
        return literal is JsonNull ? null : literal;
    }

    private static JsonValue Require(JsonObject value, string name, string path)
    {
        return value.TryGetValue(name, out var property) ? property : throw Invalid("shape", path);
    }

    private static void RequireExactKeys(JsonObject value, string path, IReadOnlyList<string> keys)
    {
        if (value.Properties.Count != keys.Count || value.Properties.Any(property => !keys.Contains(property.Name, StringComparer.Ordinal)))
        {
            throw Invalid("shape", path);
        }
    }

    private static string RequireHash(JsonValue value, string path)
    {
        return value is JsonString text ? RequireHash(text.Value, path) : throw Invalid("hash", path);
    }

    private static string RequireHash(string value, string path)
    {
        if (value.Length != 64 || value.Any(static character => !(character is >= '0' and <= '9' or >= 'a' and <= 'f')))
        {
            throw Invalid("hash", path);
        }

        return value;
    }

    private static string RequireRevision(string value, string path)
    {
        if (value.Length != 40 || value.Any(static character => !(character is >= '0' and <= '9' or >= 'a' and <= 'f')))
        {
            throw Invalid("revision", path);
        }

        return value;
    }

    private static bool JsonEquals(JsonValue? left, JsonValue? right)
    {
        if (left is null || right is null)
        {
            return left is null && right is null;
        }

        return JsonEquality.TypeAwareEquals(left, right);
    }

    private static string Sha256(ReadOnlySpan<byte> bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static AssetValidationException Invalid(string category, string path) =>
        new(category, path, "Release assets could not be validated.");
}
