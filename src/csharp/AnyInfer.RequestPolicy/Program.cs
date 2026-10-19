using AnyInfer;
using AnyInfer.Events;
using AnyInfer.Providers;
using PeterO.Numbers;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

return await RequestPolicyProgram.RunAsync(args).ConfigureAwait(false);

internal static class RequestPolicyProgram
{
    private const string Profile = "request-policy-v1";
    private const string FrozenCorpusSha256 = "92e0fc9f6e128db05719446a91b891e9ee9cacc989d97f392496a8f08e649316";
    private static readonly HashSet<string> SupportedKinds = new(StringComparer.Ordinal)
    {
        "admission", "context_route", "tool_stream", "cache", "governor", "config_policy",
    };
    private static readonly HashSet<string> SupportedProcedures = new(StringComparer.Ordinal)
    {
        "single", "retry_replacement", "fallback_handoff", "repair_no_recheck",
        "stream_early_close", "concurrent_reservation_recovery", "context_route",
        "tool_stream", "cache_sequence", "governor_body_gate", "config_consumer",
    };

    internal static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 2)
        {
            throw new ArgumentException("Expected exactly INPUT OUTPUT.");
        }

        var inputBytes = await File.ReadAllBytesAsync(args[0]).ConfigureAwait(false);
        var corpusSha = Convert.ToHexString(SHA256.HashData(inputBytes)).ToLowerInvariant();
        if (!string.Equals(corpusSha, FrozenCorpusSha256, StringComparison.Ordinal))
        {
            throw new FormatException("The observer accepts only the frozen request-policy-v1 corpus bytes.");
        }
        RejectDuplicateKeys(inputBytes);
        using var document = JsonDocument.Parse(inputBytes, StrictDocumentOptions);
        var root = document.RootElement;
        ValidateCorpus(root);

        var observations = new JsonArray();
        foreach (var item in root.GetProperty("cases").EnumerateArray())
        {
            var id = RequiredString(item, "id");
            Diagnostic(id, "case_begin");
            try
            {
                observations.Add(await PolicyCase.RunAsync(item).ConfigureAwait(false));
            }
            finally
            {
                Diagnostic(id, "case_end");
            }
        }

        var envelope = new JsonObject
        {
            ["profile"] = Profile,
            ["runtime"] = "csharp",
            ["source_revision"] = SourceRevision(),
            ["source_dirty"] = SourceDirty(),
            ["corpus_sha256"] = corpusSha,
            ["observations"] = observations,
        };
        await File.WriteAllTextAsync(args[1], envelope.ToJsonString(OutputOptions), new UTF8Encoding(false)).ConfigureAwait(false);
        return 0;
    }

    private static readonly JsonDocumentOptions StrictDocumentOptions = new()
    {
        AllowTrailingCommas = false,
        CommentHandling = JsonCommentHandling.Disallow,
    };

    internal static readonly JsonSerializerOptions OutputOptions = new() { WriteIndented = false };

    internal static void Diagnostic(string caseId, string phase) => Console.Error.WriteLine($"request-policy case={caseId} phase={phase}");

    private static void ValidateCorpus(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object ||
            !root.TryGetProperty("profile", out var profile) ||
            profile.GetString() != Profile ||
            !root.TryGetProperty("cases", out var cases) ||
            cases.ValueKind != JsonValueKind.Array ||
            cases.GetArrayLength() != 29)
        {
            throw new FormatException("The input must be the frozen request-policy-v1 corpus with 29 cases.");
        }

        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in cases.EnumerateArray())
        {
            RequireObject(item, "case");
            var id = RequiredString(item, "id");
            if (!ids.Add(id)) throw new FormatException("Case identifiers must be unique.");
            var kind = RequiredString(item, "kind");
            if (!SupportedKinds.Contains(kind)) throw new FormatException($"Unsupported request-policy kind '{kind}'.");
            var procedure = item.GetProperty("procedure");
            RequireObject(procedure, "procedure");
            var procedureName = RequiredString(procedure, "name");
            if (!SupportedProcedures.Contains(procedureName)) throw new FormatException($"Unsupported request-policy procedure '{procedureName}'.");
        }
    }

    internal static string RequiredString(JsonElement value, string name)
    {
        if (!value.TryGetProperty(name, out var member) || member.ValueKind != JsonValueKind.String || string.IsNullOrEmpty(member.GetString()))
        {
            throw new FormatException($"'{name}' must be a nonempty string.");
        }
        return member.GetString()!;
    }

    internal static string RequiredStringAllowEmpty(JsonElement value, string name)
    {
        if (!value.TryGetProperty(name, out var member) || member.ValueKind != JsonValueKind.String)
        {
            throw new FormatException($"'{name}' must be a string.");
        }
        return member.GetString()!;
    }

    internal static void RequireObject(JsonElement value, string name)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new FormatException($"'{name}' must be an object.");
    }

    internal static JsonNode? RedactJson(JsonNode? value) =>
        value is null ? null : JsonNode.Parse(Redaction.Redact(value.ToJsonString()));

    private static void RejectDuplicateKeys(ReadOnlySpan<byte> bytes)
    {
        var reader = new Utf8JsonReader(bytes, new JsonReaderOptions
        {
            AllowTrailingCommas = false,
            CommentHandling = JsonCommentHandling.Disallow,
        });
        var objectNames = new Stack<HashSet<string>>();
        while (reader.Read())
        {
            switch (reader.TokenType)
            {
                case JsonTokenType.StartObject:
                    objectNames.Push(new HashSet<string>(StringComparer.Ordinal));
                    break;
                case JsonTokenType.PropertyName:
                    var name = reader.GetString() ?? throw new FormatException("JSON property names cannot be null.");
                    if (!objectNames.Peek().Add(name)) throw new FormatException($"JSON object contains duplicate property '{name}'.");
                    break;
                case JsonTokenType.EndObject:
                    _ = objectNames.Pop();
                    break;
            }
        }
    }

    private static string SourceRevision()
    {
        var revision = typeof(Usage).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static value => value.Key == "AnyInferSourceRevision")?.Value;
        if (revision is null || revision.Length != 40 || revision.Any(static value => !((value is >= '0' and <= '9') || (value is >= 'a' and <= 'f'))))
        {
            throw new InvalidOperationException("The AnyInfer SDK must provide lowercase 40-hex AnyInferSourceRevision metadata.");
        }
        return revision;
    }

    private static bool SourceDirty()
    {
        var value = Assembly.GetEntryAssembly()?.GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(static attribute => attribute.Key == "RequestPolicySourceDirty")?.Value;
        return bool.TryParse(value, out var dirty)
            ? dirty
            : throw new InvalidOperationException("The request-policy observer requires boolean RequestPolicySourceDirty metadata.");
    }
}
