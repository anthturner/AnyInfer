using System.Globalization;
using AnyInfer.Json;

namespace AnyInfer.Conformance;

internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        return await RunAsync(args, Console.Out, Console.Error).ConfigureAwait(false);
    }

    internal static async Task<int> RunAsync(string[] args, TextWriter output, TextWriter error)
    {
        ArgumentNullException.ThrowIfNull(args);
        ArgumentNullException.ThrowIfNull(output);
        ArgumentNullException.ThrowIfNull(error);

        if (args.Length == 1 && string.Equals(args[0], "--help", StringComparison.Ordinal))
        {
            output.WriteLine("Usage: AnyInfer.Conformance --root <absolute-specification-root> [--release <relative-release>] (--verify | --development [--output <path>])");
            return 0;
        }

        var diagnosticPath = "releases/core-generation-v0.json";
        try
        {
            var options = Parse(args);
            diagnosticPath = DiagnosticPath(options.ReleasePath);
            if (options.WriteReport)
            {
                throw new AssetValidationException("unavailable", diagnosticPath, "Requested mode is not available.");
            }

            var assets = ReleaseAssetsReader.ReadAndVerify(options.RootPath!, options.ReleasePath);

            if (options.Development)
            {
                string outputPath;
                try
                {
                    outputPath = await ReportWriter.WriteDevelopmentAsync(
                        assets,
                        options.OutputPath,
                        CancellationToken.None).ConfigureAwait(false);
                }
                catch (ArgumentException)
                {
                    error.WriteLine("error output .tmp-tests");
                    return 2;
                }
                catch (UnauthorizedAccessException)
                {
                    error.WriteLine("error output .tmp-tests");
                    return 2;
                }
                catch (IOException)
                {
                    error.WriteLine("error output .tmp-tests");
                    return 2;
                }

                var document = JsonReader.Read(File.ReadAllBytes(outputPath)) as JsonObject
                    ?? throw new InvalidOperationException("Development output is not an object.");
                output.WriteLine(string.Format(CultureInfo.InvariantCulture, "development {0}", outputPath));
                return ReportWriter.HasFailureOrError(document) ? 1 : 0;
            }

            if (!options.Verify)
            {
                throw new AssetValidationException("arguments", diagnosticPath, "Verification mode is required.");
            }

            _ = FixtureReader.ReadFixtures(assets);
            output.WriteLine(string.Format(CultureInfo.InvariantCulture, "verified {0}", options.ReleasePath));
            return 0;
        }
        catch (AssetValidationException exception)
        {
            error.WriteLine(string.Format(CultureInfo.InvariantCulture, "error {0} {1}", exception.Category, SafeExceptionDiagnosticPath(exception.RelativePath)));
            return 2;
        }
    }

    private static Options Parse(IReadOnlyList<string> args)
    {
        string? root = null;
        var release = "releases/core-generation-v0.json";
        string? output = null;
        var verify = false;
        var development = false;
        var writeReport = false;
        for (var index = 0; index < args.Count; index++)
        {
            switch (args[index])
            {
                case "--root" when index + 1 < args.Count && root is null:
                    root = args[++index];
                    break;
                case "--release" when index + 1 < args.Count:
                    release = args[++index];
                    break;
                case "--output" when index + 1 < args.Count && output is null:
                    output = args[++index];
                    break;
                case "--verify":
                    verify = true;
                    break;
                case "--development":
                    development = true;
                    break;
                case "--write-report":
                    writeReport = true;
                    break;
                default:
                    throw new AssetValidationException("arguments", DiagnosticPath(release), "Invalid command line.");
            }
        }

        if (root is null || !Path.IsPathFullyQualified(root))
        {
            throw new AssetValidationException("arguments", DiagnosticPath(release), "An absolute root is required.");
        }

        if ((verify && development) || (output is not null && !development))
        {
            throw new AssetValidationException("arguments", DiagnosticPath(release), "Invalid command line.");
        }

        return new Options(root, release, output, verify, development, writeReport);
    }

    private static string SafeExceptionDiagnosticPath(string relativePath)
    {
        if (string.IsNullOrWhiteSpace(relativePath) ||
            relativePath.Length > 512 ||
            Path.IsPathFullyQualified(relativePath) ||
            relativePath.StartsWith("/", StringComparison.Ordinal) ||
            relativePath.Contains('\\') ||
            relativePath.Contains(':') ||
            relativePath.Contains('\u2028') ||
            relativePath.Contains('\u2029') ||
            relativePath.Any(char.IsControl))
        {
            return ".";
        }

        var segments = relativePath.Split('/', StringSplitOptions.None);
        return segments.Any(static segment => string.IsNullOrEmpty(segment) || segment is "." or "..")
            ? "."
            : relativePath;
    }

    private static string DiagnosticPath(string releasePath)
    {
        return SafeExceptionDiagnosticPath(releasePath);
    }

    private sealed record Options(
        string? RootPath,
        string ReleasePath,
        string? OutputPath,
        bool Verify,
        bool Development,
        bool WriteReport);
}
