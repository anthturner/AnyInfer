using AnyInfer.Capabilities;
using AnyInfer.Providers;
using System.Text;
using System.Text.Json;

var arguments = Arguments.Parse(args);
using var contextDocument = JsonDocument.Parse(await File.ReadAllBytesAsync(arguments.Context));
var context = Context.Validate(contextDocument.RootElement);
var bindings = ProviderRegistry.CreateDefault().Descriptors
    .SelectMany(descriptor => descriptor.Operations.Select(operation => new Binding(
        descriptor.Id,
        OperationName(operation),
        Dependencies(descriptor.Id))))
    .OrderBy(static binding => binding.ProviderId, StringComparer.Ordinal)
    .ThenBy(static binding => binding.Operation, StringComparer.Ordinal)
    .ToArray();

using var rendered = new MemoryStream();
using (var writer = new Utf8JsonWriter(rendered, new JsonWriterOptions { Indented = true }))
{
    writer.WriteStartObject();
    writer.WriteNumber("schema_version", 1);
    writer.WriteString("implementation_id", "anyinfer-csharp");
    writer.WritePropertyName("producer");
    writer.WriteStartObject();
    writer.WriteString("id", "csharp-provider-bindings");
    writer.WriteString("version", "1");
    writer.WriteEndObject();
    WriteContext(writer, context);
    writer.WritePropertyName("bindings");
    writer.WriteStartArray();
    foreach (var binding in bindings)
    {
        writer.WriteStartObject();
        writer.WriteString("provider_id", binding.ProviderId);
        writer.WriteString("operation", binding.Operation);
        writer.WritePropertyName("contract_dependencies");
        writer.WriteStartArray();
        foreach (var dependency in binding.Dependencies) writer.WriteStringValue(dependency);
        writer.WriteEndArray();
        writer.WriteEndObject();
    }
    writer.WriteEndArray();
    writer.WriteEndObject();
}
var bytes = rendered.ToArray();
var lf = new MemoryStream(bytes.Length + 1);
for (var index = 0; index < bytes.Length; index++)
{
    if (bytes[index] != '\r') lf.WriteByte(bytes[index]);
}
lf.WriteByte((byte)'\n');
await File.WriteAllBytesAsync(arguments.Output, lf.ToArray());

static string OperationName(InferenceOperation operation) => operation switch
{
    InferenceOperation.Generation => "generation",
    InferenceOperation.Embedding => "embedding",
    InferenceOperation.Rerank => "rerank",
    InferenceOperation.Batch => "batch",
    _ => throw new InvalidOperationException($"Registered operation {operation} has no inventory mapping."),
};

static IReadOnlyList<string> Dependencies(string providerId)
{
    IReadOnlyList<string> dependencies = providerId switch
    {
        "openai-compat" => ["contracts/openai-compat.md"],
        "tei" => ["contracts/tei.md"],
        _ => throw new InvalidOperationException($"Registered provider '{providerId}' has no checked contract dependency mapping."),
    };
    foreach (var dependency in dependencies)
    {
        if (!File.Exists(dependency)) throw new InvalidOperationException($"Mapped contract does not exist: {dependency}");
    }
    return dependencies;
}

static void WriteContext(Utf8JsonWriter writer, Context context)
{
    writer.WritePropertyName("workflow_run"); context.WorkflowRun.WriteTo(writer);
    writer.WritePropertyName("trusted_pr_head"); writer.WriteStringValue(context.TrustedPrHead);
    writer.WritePropertyName("evaluated_source"); context.EvaluatedSource.WriteTo(writer);
    writer.WriteString("registry_sha256", context.RegistrySha256);
    writer.WriteString("input_sha256", context.InputSha256);
}

internal sealed record Arguments(string Context, string Output)
{
    internal static Arguments Parse(string[] args)
    {
        if (args.Length != 4 || args[0] != "--context" || args[2] != "--output" || string.IsNullOrWhiteSpace(args[1]) || string.IsNullOrWhiteSpace(args[3]))
            throw new ArgumentException("Usage: AnyInfer.Maintenance --context CONTEXT_JSON --output OUTPUT_JSON");
        return new Arguments(args[1], args[3]);
    }
}

internal sealed record Context(JsonElement WorkflowRun, string TrustedPrHead, JsonElement EvaluatedSource, string RegistrySha256, string InputSha256)
{
    private static readonly HashSet<string> EnvelopeFields = ["schema_version", "implementation_id", "producer", "workflow_run", "trusted_pr_head", "evaluated_source", "registry_sha256", "input_sha256", "bindings"];

    internal static Context Validate(JsonElement root)
    {
        RequireObject(root, "context");
        RequireExactFields(root, EnvelopeFields, "context");
        RequireNumber(root, "schema_version", 1);
        RequireString(root, "implementation_id", "anyinfer-csharp");
        var producer = PropertyObject(root, "producer");
        RequireExactFields(producer, ["id", "version"], "producer");
        RequireString(producer, "id", "provider-change-dispatcher");
        RequireString(producer, "version", "1");
        var workflow = PropertyObject(root, "workflow_run");
        RequireExactFields(workflow, ["id", "attempt"], "workflow_run");
        RequireNonemptyString(workflow, "id");
        if (!workflow.GetProperty("attempt").TryGetInt32(out var attempt) || attempt < 1) throw Invalid("workflow_run.attempt must be a positive integer");
        var head = RequirePattern(root, "trusted_pr_head", 40);
        var source = PropertyObject(root, "evaluated_source");
        RequireExactFields(source, ["commit", "tree", "dirty", "input_fingerprint"], "evaluated_source");
        RequirePattern(source, "commit", 40); RequirePattern(source, "tree", 40); RequireBoolean(source, "dirty"); RequirePattern(source, "input_fingerprint", 64);
        var registry = RequirePattern(root, "registry_sha256", 64);
        var input = RequirePattern(root, "input_sha256", 64);
        if (root.GetProperty("bindings").ValueKind != JsonValueKind.Array || root.GetProperty("bindings").GetArrayLength() != 0) throw Invalid("context.bindings must be an empty array");
        return new Context(workflow.Clone(), head, source.Clone(), registry, input);
    }

    private static JsonElement PropertyObject(JsonElement parent, string property) => parent.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.Object ? value : throw Invalid($"{property} must be an object");
    private static void RequireObject(JsonElement value, string name) { if (value.ValueKind != JsonValueKind.Object) throw Invalid($"{name} must be an object"); }
    private static void RequireExactFields(JsonElement value, IEnumerable<string> expected, string name) { var fields = expected.ToHashSet(StringComparer.Ordinal); if (value.EnumerateObject().Any(property => !fields.Contains(property.Name)) || value.EnumerateObject().Count() != fields.Count) throw Invalid($"{name} has an invalid field set"); }
    private static void RequireNumber(JsonElement value, string property, int expected) { if (!value.TryGetProperty(property, out var number) || !number.TryGetInt32(out var actual) || actual != expected) throw Invalid($"{property} is invalid"); }
    private static void RequireString(JsonElement value, string property, string expected) { if (!value.TryGetProperty(property, out var text) || text.ValueKind != JsonValueKind.String || text.GetString() != expected) throw Invalid($"{property} is invalid"); }
    private static void RequireNonemptyString(JsonElement value, string property) { if (!value.TryGetProperty(property, out var text) || text.ValueKind != JsonValueKind.String || string.IsNullOrEmpty(text.GetString())) throw Invalid($"{property} is invalid"); }
    private static void RequireBoolean(JsonElement value, string property) { if (!value.TryGetProperty(property, out var boolean) || boolean.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw Invalid($"{property} is invalid"); }
    private static string RequirePattern(JsonElement value, string property, int length) { if (!value.TryGetProperty(property, out var text) || text.ValueKind != JsonValueKind.String || text.GetString() is not { } actual || actual.Length != length || actual.Any(static character => character is not (>= 'a' and <= 'f') and not (>= '0' and <= '9'))) throw Invalid($"{property} is invalid"); return actual; }
    private static InvalidDataException Invalid(string message) => new(message);
}

internal sealed record Binding(string ProviderId, string Operation, IReadOnlyList<string> Dependencies);
