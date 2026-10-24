using System.Numerics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using AnyInfer.Context;
using AnyInfer.Json;

return await Observer.RunAsync(args);

internal static class Observer
{
    private const string Profile = "context-tuning-v1";
    private const string FrozenSha = "122298b5b1631317db9aa93e428faa81a00ece6da9ba9694026a57cd050b30e6";
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly string[] FloatKeys = ["near_duplicate_threshold", "diversity", "expansion_weight", "salience_weight", "salience_damping", "rollup_share", "carry_over_bonus"];

    internal static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 2) throw new ArgumentException("Usage: AnyInfer.ContextTuning INPUT OUTPUT.");
        var bytes = await File.ReadAllBytesAsync(args[0]);
        if (Hash(bytes) != FrozenSha || bytes.Length == 0 || bytes[^1] != (byte)'\n' || bytes.Contains((byte)'\r') || (bytes.Length >= 3 && bytes[0] == 0xef && bytes[1] == 0xbb && bytes[2] == 0xbf)) throw new FormatException("Input is not the frozen LF corpus.");
        _ = StrictUtf8.GetString(bytes); RejectDuplicates(bytes);
        using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow });
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object || root.EnumerateObject().Count() != 3 || root.GetProperty("profile").GetString() != Profile || root.GetProperty("format_version").ValueKind != JsonValueKind.Number || root.GetProperty("format_version").GetInt32() != 1) throw new FormatException("Invalid input envelope.");
        var cases = root.GetProperty("cases").EnumerateArray().ToArray();
        if (cases.Length != 58 || cases.Select(static item => item.GetProperty("id").GetString()).Distinct(StringComparer.Ordinal).Count() != 58) throw new FormatException("Invalid case closure.");
        var observations = cases.Select(Observe).ToArray();
        var envelope = Obj(("profile", Profile), ("runtime", "csharp"), ("source_revision", SourceRevision()), ("source_dirty", SourceDirty()), ("corpus_sha256", Hash(bytes)), ("observations", observations));
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1]))!);
        await File.WriteAllTextAsync(args[1], JsonSerializer.Serialize(envelope, new JsonSerializerOptions { WriteIndented = true }) + "\n");
        return 0;
    }

    private static object Observe(JsonElement item)
    {
        var id = item.GetProperty("id").GetString()!; var kind = item.GetProperty("kind").GetString()!;
        JsonObject? values = kind is "from_mapping" or "merge" ? (JsonObject)Convert(item.GetProperty("values")) : null;
        JsonObject? baseValues = kind == "merge" ? (JsonObject)Convert(item.GetProperty("base")) : null;
        var stage = "operation";
        ContextTuning? basis = null;
        ContextTuning value;
        try
        {
            if (kind == "default") value = ContextTuning.Default;
            else if (kind == "recommended") value = ContextTuning.Recommended();
            else if (kind == "from_mapping") value = ContextTuning.FromMapping(values!);
            else if (kind == "merge") { stage = "base"; basis = ContextTuning.FromMapping(baseValues!); stage = "operation"; value = basis.Merged(values!); }
            else throw new FormatException("Unknown case kind.");
        }
        catch (Exception error) when (error is ArgumentException or ArgumentOutOfRangeException)
        {
            return Obj(("id", id), ("kind", kind), ("public", Obj(("error", Obj(("type", error.GetType().Name), ("stage", stage))))));
        }
        var mapping = Project(value.ToMapping());
        return Obj(("id", id), ("kind", kind), ("public", Obj(("mapping", mapping), ("round_trip", Project(ContextTuning.FromMapping(value.ToMapping()).ToMapping())), ("ranking_is_default", value.RankingIsDefault), ("negative_zero_fields", NegativeZeros(value.ToMapping())), ("reused_instance", basis is null ? null : ReferenceEquals(basis, value)), ("base_after", basis is null ? null : Project(basis.ToMapping())), ("constants", Obj(("default_chunk_tokens", ContextTuning.DefaultChunkTokens), ("selection_orders", ContextTuning.SelectionOrders))))));
    }

    private static JsonValue Convert(JsonElement value) => value.ValueKind switch { JsonValueKind.Null => JsonNull.Instance, JsonValueKind.True => new JsonBoolean(true), JsonValueKind.False => new JsonBoolean(false), JsonValueKind.String => new JsonString(value.GetString()!), JsonValueKind.Array => new JsonArray(value.EnumerateArray().Select(Convert)), JsonValueKind.Object => new JsonObject(value.EnumerateObject().Select(static property => new AnyInfer.Json.JsonProperty(property.Name, Convert(property.Value)))), _ => Number(value) };
    private static JsonValue Number(JsonElement value) { var raw = value.GetRawText(); return raw.IndexOfAny(['.', 'e', 'E']) < 0 ? new JsonInteger(BigInteger.Parse(raw, System.Globalization.CultureInfo.InvariantCulture)) : new JsonNumber(value.GetDouble(), raw); }
    private static JsonElement Project(JsonObject value) { using var document = JsonDocument.Parse(JsonWriter.Write(value)); return document.RootElement.Clone(); }
    private static string[] NegativeZeros(JsonObject value) => value.Properties.Where(p => FloatKeys.Contains(p.Name, StringComparer.Ordinal) && p.Value is JsonNumber n && n.IsNegativeZero).Select(p => p.Name).OrderBy(static name => name, StringComparer.Ordinal).ToArray();
    private static void RejectDuplicates(ReadOnlySpan<byte> bytes) { var reader = new Utf8JsonReader(bytes); var stack = new Stack<HashSet<string>>(); while (reader.Read()) { if (reader.TokenType == JsonTokenType.StartObject) stack.Push(new(StringComparer.Ordinal)); else if (reader.TokenType == JsonTokenType.EndObject) stack.Pop(); else if (reader.TokenType == JsonTokenType.PropertyName && !stack.Peek().Add(reader.GetString()!)) throw new FormatException("Duplicate JSON key."); } }
    private static string SourceRevision() { var value = typeof(ContextTuning).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().SingleOrDefault(static a => a.Key == "AnyInferSourceRevision")?.Value; return value is { Length: 40 } && value.All(static c => c is >= '0' and <= '9' or >= 'a' and <= 'f') ? value : throw new InvalidOperationException("AnyInferSourceRevision metadata is required."); }
    private static bool SourceDirty() { var value = Assembly.GetEntryAssembly()?.GetCustomAttributes<AssemblyMetadataAttribute>().SingleOrDefault(static a => a.Key == "ContextTuningSourceDirty")?.Value; return bool.TryParse(value, out var dirty) ? dirty : throw new InvalidOperationException("ContextTuningSourceDirty metadata is required."); }
    private static string Hash(ReadOnlySpan<byte> bytes) => System.Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static Dictionary<string, object?> Obj(params (string Key, object? Value)[] fields) => fields.ToDictionary(static field => field.Key, static field => field.Value, StringComparer.Ordinal);
}
