using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;

namespace AnyInfer.Conformance;

internal sealed record FinalReportProvenanceFacts(
    string RepositoryRoot, string ExpectedRevision, string ObservedRevision, bool IsClean,
    string DriverAssemblyPath, string LoadedLibraryAssemblyPath, string CanonicalLibraryAssemblyPath,
    string DriverSourceRevision, string LibrarySourceRevision, string Runtime, string OperatingSystem,
    IReadOnlyDictionary<string, string> Dependencies);

internal sealed class FinalReportProvenanceException : Exception
{
    internal FinalReportProvenanceException(string message) : base(message) { }
}

internal static class FinalReportProvenance
{
    private const string RevisionKey = "AnyInferSourceRevision";

    internal static FinalReportProvenanceFacts Capture(string repositoryRoot, string expectedRevision)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(repositoryRoot);
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedRevision);
        var root = Path.GetFullPath(repositoryRoot);
        var driver = typeof(Program).Assembly;
        var library = typeof(AsyncClient).Assembly;
        var driverPath = RequireAssemblyPath(driver, "driver");
        var libraryPath = RequireAssemblyPath(library, "library");
        var layout = ValidateOutputLayout(root, driverPath, libraryPath);
        var facts = new FinalReportProvenanceFacts(
            root, expectedRevision, RunGit(root, "rev-parse", "HEAD").Trim(), IsClean(root),
            driverPath, libraryPath, layout.CanonicalLibraryPath, AssemblyRevision(driver), AssemblyRevision(library),
            System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            System.Runtime.InteropServices.RuntimeInformation.OSDescription, ReadDependencies(root));
        ValidateFacts(facts);
        return facts;
    }

    internal static void ValidateFacts(FinalReportProvenanceFacts facts)
    {
        ArgumentNullException.ThrowIfNull(facts);
        if (!Path.IsPathFullyQualified(facts.RepositoryRoot) || !IsRevision(facts.ExpectedRevision) ||
            !IsRevision(facts.ObservedRevision) || !string.Equals(facts.ExpectedRevision, facts.ObservedRevision, StringComparison.Ordinal) ||
            !facts.IsClean || !string.Equals(facts.DriverSourceRevision, facts.ExpectedRevision, StringComparison.Ordinal) ||
            !string.Equals(facts.LibrarySourceRevision, facts.ExpectedRevision, StringComparison.Ordinal) ||
            string.IsNullOrWhiteSpace(facts.Runtime) || string.IsNullOrWhiteSpace(facts.OperatingSystem))
        {
            throw new FinalReportProvenanceException("Compiled-code provenance is invalid.");
        }

        var root = Path.GetFullPath(facts.RepositoryRoot);
        var layout = ValidateOutputLayout(root, facts.DriverAssemblyPath, facts.LoadedLibraryAssemblyPath);
        if (!string.Equals(Path.GetFullPath(facts.CanonicalLibraryAssemblyPath), layout.CanonicalLibraryPath, StringComparison.OrdinalIgnoreCase) ||
            IsReparsePath(facts.DriverAssemblyPath) || IsReparsePath(facts.LoadedLibraryAssemblyPath) ||
            IsReparsePath(facts.CanonicalLibraryAssemblyPath) ||
            !FilesHaveSameSha256(facts.LoadedLibraryAssemblyPath, facts.CanonicalLibraryAssemblyPath))
        {
            throw new FinalReportProvenanceException("Loaded library provenance is invalid.");
        }

        ValidateDependencies(facts.Dependencies);
    }

    internal static string RepositoryRootFromExecutable()
    {
        var start = Path.GetDirectoryName(RequireAssemblyPath(typeof(Program).Assembly, "driver"))
            ?? throw new FinalReportProvenanceException("The driver assembly has no directory.");
        var root = RunGit(start, "rev-parse", "--show-toplevel").Trim();
        if (!Path.IsPathFullyQualified(root))
        {
            throw new FinalReportProvenanceException("The executable is not inside a repository.");
        }

        return Path.GetFullPath(root);
    }

    internal static string CurrentRevision(string repositoryRoot) => RunGit(repositoryRoot, "rev-parse", "HEAD").Trim();

    internal static IReadOnlyDictionary<string, string> ReadPackageVersions(string path)
    {
        if (!File.Exists(path))
        {
            throw new FinalReportProvenanceException("Resolved package metadata is missing.");
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(path));
            return ReadPackageVersions(document.RootElement);
        }
        catch (JsonException)
        {
            throw new FinalReportProvenanceException("Resolved package metadata is malformed.");
        }
    }

    internal static IReadOnlyDictionary<string, string> ReadPackageVersions(JsonElement root)
    {
        try
        {
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("targets", out var targets) ||
                targets.ValueKind != JsonValueKind.Object || !targets.TryGetProperty("net8.0", out var target) ||
                target.ValueKind != JsonValueKind.Object || !root.TryGetProperty("libraries", out var libraries) ||
                libraries.ValueKind != JsonValueKind.Object)
            {
                throw new FinalReportProvenanceException("Resolved package metadata is malformed.");
            }

            var values = new SortedDictionary<string, string>(StringComparer.Ordinal);
            foreach (var selected in target.EnumerateObject())
            {
                if (!selected.Value.TryGetProperty("type", out var targetType) || targetType.ValueKind != JsonValueKind.String)
                {
                    throw new FinalReportProvenanceException("Resolved package metadata is malformed.");
                }

                if (!string.Equals(targetType.GetString(), "package", StringComparison.Ordinal))
                {
                    continue;
                }

                if (!libraries.TryGetProperty(selected.Name, out var catalog) || catalog.ValueKind != JsonValueKind.Object ||
                    !catalog.TryGetProperty("type", out var catalogType) || catalogType.ValueKind != JsonValueKind.String ||
                    !string.Equals(catalogType.GetString(), "package", StringComparison.Ordinal))
                {
                    throw new FinalReportProvenanceException("Resolved package metadata is malformed.");
                }

                var slash = selected.Name.LastIndexOf('/');
                if (slash <= 0 || slash == selected.Name.Length - 1)
                {
                    throw new FinalReportProvenanceException("Resolved package metadata has an invalid identity.");
                }

                var name = "nuget:" + selected.Name[..slash].ToLowerInvariant();
                var version = selected.Name[(slash + 1)..];
                if (version.Length == 0 || (!values.TryAdd(name, version) && !string.Equals(values[name], version, StringComparison.Ordinal)))
                {
                    throw new FinalReportProvenanceException("Resolved package metadata has conflicting versions.");
                }
            }

            return new Dictionary<string, string>(values, StringComparer.Ordinal);
        }
        catch (InvalidOperationException)
        {
            throw new FinalReportProvenanceException("Resolved package metadata is malformed.");
        }
    }

    private static (string CanonicalLibraryPath, string Configuration) ValidateOutputLayout(string root, string driverPath, string libraryPath)
    {
        if (!File.Exists(driverPath) || !File.Exists(libraryPath) || !IsContained(root, driverPath) || !IsContained(root, libraryPath))
        {
            throw new FinalReportProvenanceException("Loaded assembly provenance is outside the verified repository.");
        }

        var relative = Path.GetRelativePath(root, driverPath).Replace('\\', '/');
        const string prefix = "src/csharp/AnyInfer.Conformance/bin/";
        const string suffix = "/net8.0/AnyInfer.Conformance.dll";
        if (!relative.StartsWith(prefix, StringComparison.Ordinal) || !relative.EndsWith(suffix, StringComparison.Ordinal))
        {
            throw new FinalReportProvenanceException("The loaded driver is not a standard project output.");
        }

        var configuration = relative[prefix.Length..^suffix.Length];
        if (configuration.Length == 0 || configuration.Contains('/'))
        {
            throw new FinalReportProvenanceException("The loaded driver configuration is invalid.");
        }

        var canonicalLibrary = Path.GetFullPath(Path.Combine(root, "src", "csharp", "AnyInfer", "bin", configuration, "net8.0", "AnyInfer.dll"));
        var copiedLibrary = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(driverPath)!, "AnyInfer.dll"));
        if (!File.Exists(canonicalLibrary) || !IsContained(root, canonicalLibrary) ||
            !string.Equals(Path.GetFullPath(libraryPath), copiedLibrary, StringComparison.OrdinalIgnoreCase))
        {
            throw new FinalReportProvenanceException("The loaded library is not bound to the standard driver output.");
        }

        return (canonicalLibrary, configuration);
    }

    private static IReadOnlyDictionary<string, string> ReadDependencies(string root)
    {
        var driverAssets = Path.Combine(root, "src", "csharp", "AnyInfer.Conformance", "obj", "project.assets.json");
        var libraryAssets = Path.Combine(root, "src", "csharp", "AnyInfer", "obj", "project.assets.json");
        var library = ReadPackageVersions(libraryAssets);
        if (library.Count != 0)
        {
            throw new FinalReportProvenanceException("The runtime library has package dependencies.");
        }

        return ReadPackageVersions(driverAssets);
    }

    private static void ValidateDependencies(IReadOnlyDictionary<string, string> dependencies)
    {
        var identities = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in dependencies)
        {
            if (!IsCanonicalPackageKey(pair.Key) || string.IsNullOrWhiteSpace(pair.Value) || !identities.Add(pair.Key))
            {
                throw new FinalReportProvenanceException("Resolved dependency provenance is invalid.");
            }
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

    private static string AssemblyRevision(Assembly assembly)
    {
        var values = assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .Where(attribute => string.Equals(attribute.Key, RevisionKey, StringComparison.Ordinal))
            .Select(attribute => attribute.Value)
            .ToArray();
        if (values.Length != 1 || values[0] is not string value || !IsRevision(value))
        {
            throw new FinalReportProvenanceException("Assembly source revision metadata is invalid.");
        }

        return value;
    }

    private static string RequireAssemblyPath(Assembly assembly, string kind)
    {
        if (string.IsNullOrWhiteSpace(assembly.Location) || !Path.IsPathFullyQualified(assembly.Location))
        {
            throw new FinalReportProvenanceException("The loaded " + kind + " assembly has no local path.");
        }

        return Path.GetFullPath(assembly.Location);
    }

    private static bool IsClean(string root) => string.IsNullOrEmpty(RunGit(root, "status", "--porcelain", "--untracked-files=all"));

    private static string RunGit(string workingDirectory, params string[] arguments)
    {
        var start = new ProcessStartInfo("git") { WorkingDirectory = workingDirectory, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, CreateNoWindow = true };
        foreach (var argument in arguments)
        {
            start.ArgumentList.Add(argument);
        }

        using var process = Process.Start(start) ?? throw new FinalReportProvenanceException("Git provenance inspection could not start.");
        var output = process.StandardOutput.ReadToEnd();
        _ = process.StandardError.ReadToEnd();
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            throw new FinalReportProvenanceException("Git provenance inspection failed.");
        }

        return output;
    }

    private static bool FilesHaveSameSha256(string first, string second) => File.Exists(first) && File.Exists(second) &&
        SHA256.HashData(File.ReadAllBytes(first)).SequenceEqual(SHA256.HashData(File.ReadAllBytes(second)));

    private static bool IsRevision(string value) => value.Length == 40 && value.All(static character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static bool IsContained(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        return !Path.IsPathFullyQualified(relative) && relative != ".." && !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) && !relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal);
    }

    private static bool IsReparsePath(string path)
    {
        var current = Path.GetPathRoot(path) ?? string.Empty;
        foreach (var part in path[current.Length..].Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
        {
            if (part.Length != 0)
            {
                current = Path.Combine(current, part);
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                {
                    return true;
                }
            }
        }

        return false;
    }
}
