using System.Text.Json;
using System.Text.RegularExpressions;
using AnyInfer.Internal;
using AnyInfer.Json;
using Json.Schema;

namespace AnyInfer.Schema;

/// <summary>Retrieves an explicitly allowed external schema resource.</summary>
/// <remarks>
/// Validation calls the retriever only for a referenced resource that is not registered in
/// <see cref="SchemaValidationOptions.Resources"/>, at most once per resource URI in one
/// validation. A retrieved document is used for that validation only and is not cached.
/// </remarks>
/// <param name="resourceUri">The fragment-free resource URI.</param>
/// <param name="cancellationToken">Cancellation for the retrieval operation.</param>
/// <returns>
/// The resource document, or <see langword="null"/> when unavailable, which fails validation
/// with <see cref="SchemaReferenceException"/>.
/// </returns>
public delegate ValueTask<JsonValue?> SchemaResourceRetriever(Uri resourceUri, CancellationToken cancellationToken);

/// <summary>Controls modern JSON Schema validation resources and limits.</summary>
/// <remarks>
/// Validation never fetches a resource implicitly: a reference resolves only to the schema
/// itself or one of its embedded resources, the bundled meta-schemas of the supported dialects,
/// a document in <see cref="Resources"/>, or a document returned by <see cref="Retrieve"/>. The same options can be passed to
/// <see cref="SchemaValidator.ValidateAsync(JsonValue, SchemaSpec, SchemaValidationOptions, CancellationToken)"/>
/// or to a client for structured-output validation.
/// </remarks>
public sealed class SchemaValidationOptions
{
    /// <summary>Initializes validation options with copied resource bindings.</summary>
    /// <param name="resources">
    /// Schema documents keyed by absolute URI without a fragment, or <see langword="null"/> for
    /// none. The mapping is copied.
    /// </param>
    /// <param name="retrieve">
    /// Callback for referenced resources missing from <paramref name="resources"/>, or
    /// <see langword="null"/> so that such references fail with <see cref="SchemaReferenceException"/>.
    /// </param>
    /// <param name="baseUri">
    /// Absolute URI that identifies a root schema without <c>$id</c> and against which a
    /// relative root <c>$id</c> resolves, or <see langword="null"/> to use a
    /// <c>urn:anyinfer:schema:</c> URN derived from the schema's SHA-256 digest.
    /// </param>
    /// <param name="regexTimeout">
    /// Timeout applied to each individual <c>pattern</c> or <c>patternProperties</c> regular
    /// expression match, or <see langword="null"/> for one second. It is not an overall
    /// evaluation deadline. It must be positive and at most <see cref="int.MaxValue"/> - 1
    /// milliseconds.
    /// </param>
    /// <exception cref="ArgumentException">
    /// <paramref name="baseUri"/> is relative, or a resource key is relative or has a fragment, or a
    /// resource value is <see langword="null"/>.
    /// </exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="regexTimeout"/> is outside the allowed range.</exception>
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
/// <param name="Rule">
/// The failing keyword, such as <c>type</c> or <c>required</c>; <c>$schema</c> for an
/// unsupported dialect; or <c>invalid_schema</c> when the schema could not be built.
/// </param>
/// <param name="InstanceLocation">
/// JSON Pointer to the failing part of the instance (empty for the root), or
/// <see langword="null"/> for a schema-definition failure.
/// </param>
/// <param name="SchemaLocation">
/// Location of the failing schema keyword as reported by the native evaluator, usually an
/// absolute URI with a JSON Pointer fragment, or <see langword="null"/> when not reported.
/// </param>
/// <param name="Message">The human-readable diagnostic produced by the native evaluator.</param>
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
    /// <summary>Native validity, retained even when the validator emits no flattened issue; always <see langword="false"/> for an invalid schema.</summary>
    public bool IsValid { get; }
    /// <summary>
    /// Diagnostics in native output order, capped at <see cref="SchemaValidator.MaxReportedErrors"/>
    /// entries; may be empty even when <see cref="IsValid"/> is <see langword="false"/>.
    /// </summary>
    public IReadOnlyList<SchemaValidationIssue> Issues { get; }
    /// <summary>Messages corresponding to <see cref="Issues"/>.</summary>
    public IReadOnlyList<string> Messages { get; }
}

/// <summary>Modern JSON Schema validation entry point.</summary>
/// <remarks>
/// Supported dialects are Draft 6, Draft 7, Draft 2019-09 and Draft 2020-12; Draft 3 and
/// Draft 4 are not supported. Numeric and regular-expression behavior is native to .NET:
/// <c>pattern</c> and <c>patternProperties</c> use .NET regular expressions with a per-match
/// timeout, and numeric <c>const</c>, <c>enum</c> and <c>uniqueItems</c> comparisons use .NET
/// <see cref="decimal"/>, so values outside that range, such as <c>1e70</c>, fail with
/// <see cref="SchemaEvaluationException"/>. Schemas and instances otherwise retain
/// arbitrary-size integers.
/// </remarks>
public static class SchemaValidator
{
    /// <summary>
    /// Maximum number of diagnostics a validation result reports, which is also the number of
    /// findings selected for schema repair feedback.
    /// </summary>
    public const int MaxReportedErrors = 5;
    /// <summary>Validates an instance against a modern JSON Schema without implicit retrieval.</summary>
    /// <remarks>
    /// The dialect is chosen by the schema's <c>$schema</c> keyword; a schema without one, or a
    /// schema that is not an object, is evaluated as Draft 2020-12. The schema is first checked
    /// against its dialect's meta-schema, and an unsupported <c>$schema</c> or a schema that fails
    /// that check produces a <see cref="SchemaValidationKind.InvalidSchema"/> result instead of an
    /// exception. During instance validation <c>format</c> is treated as an annotation and is not
    /// asserted. External references resolve only through <paramref name="options"/>.
    /// </remarks>
    /// <param name="value">The instance to validate.</param>
    /// <param name="schema">The schema specification; only its <see cref="SchemaSpec.JsonSchema"/> document is used.</param>
    /// <param name="options">
    /// Resource bindings, retrieval callback, base URI and regex timeout, or <see langword="null"/>
    /// for no resources, no retrieval and a one-second per-match regex timeout.
    /// </param>
    /// <param name="cancellationToken">
    /// Cancels validation; it is checked before evaluation and after each retrieval and is passed
    /// to <see cref="SchemaValidationOptions.Retrieve"/>.
    /// </param>
    /// <returns>
    /// A <see cref="SchemaValidationKind.Validation"/> result whose <see cref="SchemaValidationResult.IsValid"/>
    /// reports the outcome, or a <see cref="SchemaValidationKind.InvalidSchema"/> result.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="value"/> or <paramref name="schema"/> is <see langword="null"/>.</exception>
    /// <exception cref="SchemaReferenceException">
    /// A reference cannot be resolved: the resource is not registered and no retriever is set, the
    /// retriever returned <see langword="null"/>, or distinct documents claim the same resource URI.
    /// </exception>
    /// <exception cref="SchemaEvaluationException">
    /// The native evaluator cannot represent or evaluate the schema or instance, including a
    /// regular-expression match that exceeds the configured timeout.
    /// </exception>
    /// <exception cref="OperationCanceledException"><paramref name="cancellationToken"/> was cancelled.</exception>
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
