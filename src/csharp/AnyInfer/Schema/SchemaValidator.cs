using System.Text.Json;
using System.Text.RegularExpressions;
using AnyInfer.Internal;
using AnyInfer.Json;
using Json.Schema;

namespace AnyInfer.Schema;

/// <summary>Retrieves an explicitly allowed external schema resource.</summary>
/// <param name="resourceUri">The fragment-free resource URI.</param>
/// <param name="cancellationToken">Cancellation for the retrieval operation.</param>
/// <returns>The resource document, or <see langword="null"/> when unavailable.</returns>
public delegate ValueTask<JsonValue?> SchemaResourceRetriever(Uri resourceUri, CancellationToken cancellationToken);

/// <summary>Controls modern JSON Schema validation resources and limits.</summary>
public sealed class SchemaValidationOptions
{
    /// <summary>Initializes validation options with copied resource bindings.</summary>
    public SchemaValidationOptions(IReadOnlyDictionary<Uri, JsonValue>? resources = null, SchemaResourceRetriever? retrieve = null, Uri? baseUri = null, TimeSpan? regexTimeout = null)
    {
        if (baseUri is not null && !baseUri.IsAbsoluteUri) throw new ArgumentException("The schema base URI must be absolute.", nameof(baseUri));
        BaseUri = baseUri; Retrieve = retrieve; RegexTimeout = ValidateTimeout(regexTimeout ?? TimeSpan.FromSeconds(1));
        var copy = new Dictionary<Uri, JsonValue>();
        foreach (var pair in resources ?? new Dictionary<Uri, JsonValue>())
        {
            if (!pair.Key.IsAbsoluteUri || !string.IsNullOrEmpty(pair.Key.Fragment) || pair.Value is null) throw new ArgumentException("Schema resources require absolute fragment-free URIs and non-null values.", nameof(resources));
            var key = WithoutFragment(pair.Key); if (!copy.TryAdd(key, pair.Value)) throw new ArgumentException("Schema resource identities must be unique.", nameof(resources));
        }
        Resources = new System.Collections.ObjectModel.ReadOnlyDictionary<Uri, JsonValue>(copy);
    }
    /// <summary>Copied fragment-free caller resource bindings.</summary>
    public IReadOnlyDictionary<Uri, JsonValue> Resources { get; }
    /// <summary>Optional callback for explicitly permitted external resources.</summary>
    public SchemaResourceRetriever? Retrieve { get; }
    /// <summary>Optional absolute base URI for a root schema without an identifier.</summary>
    public Uri? BaseUri { get; }
    /// <summary>Positive per-match regex timeout, not an overall evaluation deadline.</summary>
    public TimeSpan RegexTimeout { get; }
    private static TimeSpan ValidateTimeout(TimeSpan value) => value <= TimeSpan.Zero || value.TotalMilliseconds > int.MaxValue - 1 ? throw new ArgumentOutOfRangeException(nameof(value)) : value;
    private static Uri WithoutFragment(Uri value) => new UriBuilder(value) { Fragment = string.Empty }.Uri;
    private static Uri CanonicalUri(JsonValue document, Uri requested) => document is JsonObject obj && obj.TryGetValue("$id", out var id) && id is JsonString { Value.Length: > 0 } text && Uri.TryCreate(requested, text.Value, out var uri) && uri.IsAbsoluteUri ? WithoutFragment(uri) : requested;
}

/// <summary>Distinguishes instance validation from schema-definition failure.</summary>
public enum SchemaValidationKind
{
    /// <summary>The supplied schema was evaluated against an instance.</summary>
    Validation,
    /// <summary>The supplied schema is invalid or unsupported.</summary>
    InvalidSchema,
}
/// <summary>A validation diagnostic with native JSON Pointer locations when available.</summary>
public sealed record SchemaValidationIssue(
    string Rule,
    string? InstanceLocation,
    string? SchemaLocation,
    string Message);
/// <summary>Immutable outcome of a schema assessment.</summary>
public sealed class SchemaValidationResult
{
    internal SchemaValidationResult(SchemaValidationKind kind, IEnumerable<SchemaValidationIssue> issues, bool? isValid = null)
    { Kind = kind; var copy = issues.ToArray(); Issues = Array.AsReadOnly(copy); Messages = Array.AsReadOnly(copy.Select(static x => x.Message).ToArray()); IsValid = isValid ?? (kind == SchemaValidationKind.Validation && copy.Length == 0); }
    /// <summary>Whether the result is an instance validation or invalid-schema outcome.</summary>
    public SchemaValidationKind Kind { get; }
    /// <summary>Native validity, retained even when the validator emits no flattened issue.</summary>
    public bool IsValid { get; }
    /// <summary>Copied diagnostics, capped only when projected into repair assessment.</summary>
    public IReadOnlyList<SchemaValidationIssue> Issues { get; }
    /// <summary>Messages corresponding to <see cref="Issues"/>.</summary>
    public IReadOnlyList<string> Messages { get; }
}

/// <summary>Modern JSON Schema validation entry point.</summary>
public static class SchemaValidator
{
    /// <summary>Maximum findings selected for schema repair assessment.</summary>
    public const int MaxReportedErrors = 5;
    /// <summary>Validates an instance against a modern JSON Schema without implicit retrieval.</summary>
    public static Task<SchemaValidationResult> ValidateAsync(JsonValue value, SchemaSpec schema, SchemaValidationOptions? options = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(value);
        ArgumentNullException.ThrowIfNull(schema);
        return ValidateCoreAsync(value, schema, options ?? new SchemaValidationOptions(), null, cancellationToken);
    }
    private static async Task<SchemaValidationResult> ValidateCoreAsync(JsonValue value, SchemaSpec schema, SchemaValidationOptions options, string? provider, CancellationToken token)
    {
        ThrowOwned(token); var dialect = SelectDialect(schema.JsonSchema);
        if (dialect is null) return Invalid("$schema", "Only Draft 6, Draft 7, Draft 2019-09, and Draft 2020-12 are supported.", SchemaLocation(schema, options) + "#/$schema");
        var resources = options.Resources.ToDictionary(static p => p.Key, static p => p.Value); var attempted = new HashSet<Uri>();
        while (true)
        {
            ModernSchemaEngine.MissingResource? missing = null;
            try { return new ModernSchemaEngine(new SchemaValidationOptions(resources, options.Retrieve, options.BaseUri, options.RegexTimeout), dialect).Evaluate(value, schema, token); }
            catch (ModernSchemaEngine.EvaluationFailure ex)
            {
                throw new SchemaEvaluationException(
                    "The native schema evaluator could not represent or evaluate this schema.",
                    provider,
                    ex.NativeInner);
            }
            catch (ModernSchemaEngine.ReferenceFailure ex)
            {
                throw new SchemaReferenceException(
                    "The schema reference could not be resolved.",
                    WithoutFragment(ex.ResourceUri),
                    ex.Fragment,
                    provider,
                    ex.NativeInner);
            }
            catch (ModernSchemaEngine.MissingResource ex) { missing = ex; }
            catch (RegexMatchTimeoutException ex) { throw new SchemaEvaluationException("Schema evaluation exceeded the configured regex timeout.", provider, ex); }
            catch (RefResolutionException ex) { throw ReferenceFailure(ex.BaseUri, ex.Anchor, provider, ex); }
            catch (JsonSchemaException ex) { return Invalid("invalid_schema", ex.Message, SchemaLocation(schema, options)); }
            var requested = WithoutFragment(missing!.Uri);
            if (resources.ContainsKey(requested) || options.Retrieve is null || !attempted.Add(requested)) throw new SchemaReferenceException("The schema references an unregistered resource.", requested, missing.Uri.Fragment, provider, missing);
            var fetched = await options.Retrieve(requested, token).ConfigureAwait(false); ThrowOwned(token);
            if (fetched is null) throw new SchemaReferenceException("The schema resource retriever returned no document.", requested, missing.Uri.Fragment, provider, missing);
            resources[requested] = fetched;
        }
    }
    internal static async Task<NativeAssessment> AssessResponseAsync(SchemaSpec schema, string text, Guid operationId, int ordinal, SchemaValidationOptions? options, string? provider, CancellationToken token)
    {
        ThrowOwned(token); var extraction = ResponseExtractor.ExtractModern(text);
        if (extraction.Failure is { } failure) return new NativeAssessment(operationId, ordinal, "extraction", null, [failure], [failure]);
        var result = await ValidateCoreAsync(extraction.Value!, schema, options ?? new SchemaValidationOptions(), provider, token).ConfigureAwait(false); ThrowOwned(token);
        var findings = result.IsValid ? new List<NativeFinding>() : result.Issues.Select(ToFinding).ToList();
        if (!result.IsValid && findings.Count == 0)
        {
            findings.Add(new NativeFinding(
                new Issue(result.Kind == SchemaValidationKind.InvalidSchema ? "invalid_schema" : "schema_validation"),
                "Schema validation failed without diagnostics.",
                "schema-validator",
                new JsonObject([])));
        }

        var kind = result.Kind == SchemaValidationKind.InvalidSchema ? "invalid_schema" : "validation";
        return new NativeAssessment(operationId, ordinal, kind, extraction.Value, findings, findings.Take(MaxReportedErrors), result.IsValid);
    }
    private static NativeFinding ToFinding(SchemaValidationIssue issue)
    {
        var facts = new List<AnyInfer.Json.JsonProperty>();
        if (issue.InstanceLocation is not null) facts.Add(new AnyInfer.Json.JsonProperty("instance_location", new JsonString(issue.InstanceLocation)));
        if (issue.SchemaLocation is not null) facts.Add(new AnyInfer.Json.JsonProperty("schema_location", new JsonString(issue.SchemaLocation)));
        return new NativeFinding(new Issue(issue.Rule), issue.Message, "schema-validator", new JsonObject(facts));
    }
    private static void ThrowOwned(CancellationToken token) { var original = CancellationIdentityContext.Resolve(token); if (original.IsCancellationRequested) throw new OperationCanceledException(original); token.ThrowIfCancellationRequested(); }
    private static SchemaValidationResult Invalid(string rule, string message, string? location = null) => new(SchemaValidationKind.InvalidSchema, [new SchemaValidationIssue(rule, null, location, message)]);
    private static string SchemaLocation(SchemaSpec schema, SchemaValidationOptions options)
    {
        var fallback = new Uri("urn:anyinfer:schema:" + Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(JsonWriter.WriteCanonicalModern(schema.JsonSchema)))).ToLowerInvariant());
        return CanonicalUri(schema.JsonSchema, options.BaseUri ?? fallback).AbsoluteUri;
    }
    private static SchemaReferenceException ReferenceFailure(Uri baseUri, string? anchor, string? provider, Exception inner)
    {
        var fragment = !string.IsNullOrEmpty(anchor) ? anchor : string.IsNullOrEmpty(baseUri.Fragment) ? null : baseUri.Fragment;
        return new SchemaReferenceException("The schema reference could not be resolved.", WithoutFragment(baseUri), fragment, provider, inner);
    }
    private static Uri WithoutFragment(Uri value) => new UriBuilder(value) { Fragment = string.Empty }.Uri;
    private static Uri CanonicalUri(JsonValue document, Uri requested) => document is JsonObject obj && obj.TryGetValue("$id", out var id) && id is JsonString { Value.Length: > 0 } text && Uri.TryCreate(requested, text.Value, out var uri) && uri.IsAbsoluteUri ? WithoutFragment(uri) : requested;
    private static Dialect? SelectDialect(JsonValue schema)
    { if (schema is not JsonObject obj || !obj.TryGetValue("$schema", out var value)) return Dialect.Draft202012; if (value is not JsonString text || !Uri.TryCreate(text.Value, UriKind.Absolute, out var uri)) return null; var selected = WithoutFragment(uri); return selected == MetaSchemas.Draft6Id ? Dialect.Draft06 : selected == MetaSchemas.Draft7Id ? Dialect.Draft07 : selected == MetaSchemas.Draft201909Id ? Dialect.Draft201909 : selected == MetaSchemas.Draft202012Id ? Dialect.Draft202012 : null; }
}
