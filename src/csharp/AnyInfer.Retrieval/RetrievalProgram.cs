using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using AnyInfer;
using AnyInfer.Json;

internal static class RetrievalProgram
{
    private const string Profile = "retrieval-v1";

    internal static async Task<int> RunAsync(string[] args)
    {
        var options = ParseArguments(args);
        var inputBytes = await File.ReadAllBytesAsync(options.Input).ConfigureAwait(false);
        if (inputBytes.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }))
        {
            throw new FormatException("The retrieval input must be UTF-8 without a BOM.");
        }
        RejectDuplicateKeys(inputBytes);
        using var document = JsonDocument.Parse(inputBytes, StrictDocumentOptions);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object ||
            root.GetProperty("profile").GetString() != Profile ||
            root.GetProperty("cases").ValueKind != JsonValueKind.Array)
        {
            throw new FormatException("Expected a retrieval-v1 input envelope.");
        }

        var observations = new List<JsonValue>();
        foreach (var item in root.GetProperty("cases").EnumerateArray())
        {
            observations.Add(await RetrievalCase.ObserveAsync(item).ConfigureAwait(false));
        }

        var output = FixtureJson.Object(
            ("profile", FixtureJson.String(Profile)),
            ("runtime", FixtureJson.String("csharp")),
            ("source_revision", FixtureJson.String(SourceRevision())),
            ("source_dirty", FixtureJson.Boolean(SourceDirty())),
            ("corpus_sha256", FixtureJson.String(Convert.ToHexString(SHA256.HashData(inputBytes)).ToLowerInvariant())),
            ("observations", FixtureJson.Array(observations)));
        FixtureJson.WriteToFile(options.Output, output);
        return 0;
    }

    internal static readonly JsonDocumentOptions StrictDocumentOptions = new()
    {
        AllowTrailingCommas = false,
        CommentHandling = JsonCommentHandling.Disallow,
    };

    private static Options ParseArguments(IReadOnlyList<string> args)
    {
        if (args.Count != 2)
        {
            throw new ArgumentException("Usage: AnyInfer.Retrieval INPUT OUTPUT.");
        }

        return new Options(args[0], args[1]);
    }

    private static void RejectDuplicateKeys(ReadOnlySpan<byte> source)
    {
        var reader = new Utf8JsonReader(source, new JsonReaderOptions { CommentHandling = JsonCommentHandling.Disallow });
        var names = new Stack<HashSet<string>>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.StartObject) names.Push(new HashSet<string>(StringComparer.Ordinal));
            else if (reader.TokenType == JsonTokenType.EndObject) names.Pop();
            else if (reader.TokenType == JsonTokenType.PropertyName && !names.Peek().Add(reader.GetString()!))
            {
                throw new FormatException("The retrieval input contains a duplicate JSON object key.");
            }
        }
    }

    private static string SourceRevision()
    {
        var value = typeof(AsyncClient).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "AnyInferSourceRevision")?.Value;
        return value is { Length: 40 } && value.All(static c => c is >= '0' and <= '9' or >= 'a' and <= 'f')
            ? value : throw new InvalidOperationException("AnyInferSourceRevision metadata is required.");
    }

    private static bool SourceDirty()
    {
        var value = Assembly.GetEntryAssembly()?.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "RetrievalSourceDirty")?.Value;
        return bool.TryParse(value, out var dirty)
            ? dirty : throw new InvalidOperationException("RetrievalSourceDirty metadata is required.");
    }

    private sealed record Options(string Input, string Output);
}
