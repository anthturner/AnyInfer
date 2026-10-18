using System.Text.Json;
using System.Text.RegularExpressions;
using AnyInfer.Internal;
using AnyInfer.Json;
using Json.Pointer;
using Json.Schema;
using Json.Schema.Keywords;

namespace AnyInfer.Schema;

// All JsonSchema.Net state is assessment-local. This type deliberately owns every
// compiled document it evaluates, including the copied meta-schema documents.
internal sealed class ModernSchemaEngine
{
    private readonly SchemaValidationOptions _options;
    private readonly BuildOptions _build;
    private readonly List<DecoratedDocument> _documents = [];

    internal ModernSchemaEngine(SchemaValidationOptions options, Dialect dialect)
    {
        _options = options;
        _build = new BuildOptions
        {
            SchemaRegistry = new SchemaRegistry(),
            VocabularyRegistry = new VocabularyRegistry(),
            DialectRegistry = new DialectRegistry(),
            Dialect = dialect,
        };
        _build.SchemaRegistry.Fetch = static (uri, _) => throw new MissingResource(uri);
    }

    internal SchemaValidationResult Evaluate(JsonValue value, SchemaSpec schema, CancellationToken cancellationToken)
    {
        var original = CancellationIdentityContext.Resolve(cancellationToken);
        if (original.IsCancellationRequested)
        {
            throw new OperationCanceledException(original);
        }

        cancellationToken.ThrowIfCancellationRequested();
        var bindings = BindDocuments(schema);
        var selectedMeta = bindings.SelectedMeta.Document!;
        var root = bindings.Root.Document!;
        using var schemaInstance = JsonDocument.Parse(JsonWriter.WriteModern(schema.JsonSchema));

        var metaWrapper = CreateWrapper(selectedMeta.BaseUri, "meta");
        AssertOwned(metaWrapper.Root, true);
        EvaluationResults metaResult;
        try
        {
            metaResult = metaWrapper.Evaluate(schemaInstance.RootElement, new EvaluationOptions
            {
                OutputFormat = OutputFormat.Hierarchical,
                RequireFormatValidation = true,
            });
        }
        catch (FormatException ex)
        {
            throw new EvaluationFailure(ex);
        }
        if (!metaResult.IsValid)
        {
            return InvalidSchemaResult(metaResult, root.BaseUri);
        }

        var wrapper = CreateWrapper(root.BaseUri, "instance");
        AssertOwned(wrapper.Root, true);
        using var instance = JsonDocument.Parse(JsonWriter.WriteModern(value));
        EvaluationResults result;
        try
        {
            result = wrapper.Evaluate(instance.RootElement, new EvaluationOptions
            {
                OutputFormat = OutputFormat.Hierarchical,
                RequireFormatValidation = false,
            });
        }
        catch (FormatException ex)
        {
            throw new EvaluationFailure(ex);
        }
        return ValidationResult(result);
    }

    private BoundDocuments BindDocuments(SchemaSpec schema)
    {
        var candidates = MetaCandidates().ToList();
        var requestedRoot = _options.BaseUri ?? DefaultUri(schema.JsonSchema);
        candidates.Add(DocumentCandidate.FromJson(requestedRoot, schema.JsonSchema));
        foreach (var resource in _options.Resources)
        {
            candidates.Add(DocumentCandidate.FromJson(resource.Key, resource.Value));
        }

        var canonical = new Dictionary<Uri, PlannedDocument>();
        var aliases = new Dictionary<Uri, PlannedDocument>();
        foreach (var candidate in candidates)
        {
            if (!canonical.TryGetValue(candidate.CanonicalUri, out var planned))
            {
                planned = new PlannedDocument(candidate.CanonicalUri, candidate.Source, candidate.Content, candidate.IsMeta);
                canonical.Add(candidate.CanonicalUri, planned);
            }
            else if (planned.IsMeta != candidate.IsMeta)
            {
                throw Conflict(candidate.CanonicalUri, "A caller schema cannot replace a private meta-schema document.");
            }
            else if (!string.Equals(planned.Content, candidate.Content, StringComparison.Ordinal))
            {
                throw Conflict(candidate.CanonicalUri, "Distinct schema documents claim the same canonical resource URI.");
            }

            AddAlias(aliases, candidate.RequestedUri, planned);
            AddAlias(aliases, candidate.CanonicalUri, planned);
        }

        foreach (var planned in canonical.Values)
        {
            planned.Document = new DecoratedDocument(planned.Source, planned.CanonicalUri, _options.RegexTimeout);
            _documents.Add(planned.Document);
        }
        foreach (var alias in aliases)
        {
            _build.SchemaRegistry.Register(alias.Key, alias.Value.Document!);
        }

        var root = canonical[CanonicalUri(schema.JsonSchema, requestedRoot)];
        var selectedMeta = canonical[SelectedMetaUri(_build.Dialect)];
        return new BoundDocuments(root, selectedMeta);
    }

    private static void AddAlias(Dictionary<Uri, PlannedDocument> aliases, Uri alias, PlannedDocument planned)
    {
        if (aliases.TryGetValue(alias, out var existing) && !ReferenceEquals(existing, planned))
        {
            throw Conflict(alias, "A schema resource alias would overwrite a distinct document.");
        }

        aliases[alias] = planned;
    }

    private global::Json.Schema.JsonSchema CreateWrapper(Uri target, string purpose)
    {
        var wrapper = "{\"$ref\":" + JsonSerializer.Serialize(target.ToString()) + "}";
        try
        {
            return global::Json.Schema.JsonSchema.FromText(
                wrapper,
                _build,
                new Uri("urn:anyinfer:schema:" + purpose + ":" + Guid.NewGuid().ToString("N")));
        }
        catch (FormatException ex)
        {
            throw new EvaluationFailure(ex);
        }
    }

    private SchemaValidationResult ValidationResult(EvaluationResults result)
    {
        var issues = Flatten(result)
            .SelectMany(static entry => entry.Errors is null
                ? []
                : entry.Errors.Select(error => new SchemaValidationIssue(
                    error.Key,
                    entry.InstanceLocation.ToString(),
                    entry.SchemaLocation.ToString(),
                    error.Value)))
            .Take(SchemaValidator.MaxReportedErrors);
        return new SchemaValidationResult(SchemaValidationKind.Validation, issues, result.IsValid);
    }

    private SchemaValidationResult InvalidSchemaResult(EvaluationResults result, Uri canonicalSchema)
    {
        var issues = Flatten(result)
            .SelectMany(entry => entry.Errors is null
                ? []
                : entry.Errors.Select(error => new SchemaValidationIssue(
                    error.Key,
                    null,
                    CanonicalSchemaLocation(canonicalSchema, entry.InstanceLocation),
                    error.Value)))
            .Take(SchemaValidator.MaxReportedErrors)
            .ToArray();
        if (issues.Length == 0)
        {
            issues = [new SchemaValidationIssue(
                "invalid_schema",
                null,
                canonicalSchema.ToString(),
                "The schema is invalid for its selected dialect.")];
        }

        return new SchemaValidationResult(SchemaValidationKind.InvalidSchema, issues);
    }

    private static string CanonicalSchemaLocation(Uri baseUri, JsonPointer location)
    {
        var pointer = location.ToString();
        return string.IsNullOrEmpty(pointer) ? baseUri.ToString() : baseUri.ToString() + "#" + pointer;
    }

    private static IEnumerable<DocumentCandidate> MetaCandidates()
    {
        foreach (var schema in new[]
        {
            MetaSchemas.Draft6, MetaSchemas.Draft7, MetaSchemas.Applicator201909, MetaSchemas.Content201909,
            MetaSchemas.Core201909, MetaSchemas.Format201909, MetaSchemas.Metadata201909, MetaSchemas.Validation201909,
            MetaSchemas.Draft201909, MetaSchemas.Applicator202012, MetaSchemas.Content202012, MetaSchemas.Core202012,
            MetaSchemas.FormatAnnotation202012, MetaSchemas.FormatAssertion202012, MetaSchemas.Metadata202012,
            MetaSchemas.Unevaluated202012, MetaSchemas.Validation202012, MetaSchemas.Draft202012,
        })
        {
            var value = JsonReader.Read(schema.Root.Source.GetRawText());
            var source = Parse(JsonWriter.WriteModern(value));
            yield return new DocumentCandidate(
                schema.BaseUri,
                schema.BaseUri,
                source,
                JsonWriter.WriteCanonicalModern(value),
                true);
        }
    }

    private void AssertOwned(JsonSchemaNode node, bool wrapper)
    {
        var visited = new HashSet<JsonSchemaNode>(ReferenceEqualityComparer.Instance);
        var pending = new Stack<(JsonSchemaNode Node, bool Wrapper)>();
        pending.Push((node, wrapper));
        while (pending.Count != 0)
        {
            var current = pending.Pop();
            if (!visited.Add(current.Node)) continue;
            if (!current.Wrapper && !_documents.Any(document => document.Owns(current.Node)))
            {
                throw new ReferenceFailure(
                    current.Node.BaseUri,
                    null,
                    new InvalidOperationException("Resolved schema graph contains an unowned compiled node."));
            }

            foreach (var keyword in current.Node.Keywords)
            {
                foreach (var child in keyword.Subschemas)
                {
                    pending.Push((child, false));
                }
            }
        }
    }

    private static Uri SelectedMetaUri(Dialect dialect)
    {
        if (ReferenceEquals(dialect, Dialect.Draft06)) return MetaSchemas.Draft6Id;
        if (ReferenceEquals(dialect, Dialect.Draft07)) return MetaSchemas.Draft7Id;
        if (ReferenceEquals(dialect, Dialect.Draft201909)) return MetaSchemas.Draft201909Id;
        if (ReferenceEquals(dialect, Dialect.Draft202012)) return MetaSchemas.Draft202012Id;
        throw new ArgumentOutOfRangeException(nameof(dialect));
    }

    private static Uri DefaultUri(JsonValue schema)
    {
        var hash = System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(JsonWriter.WriteCanonicalModern(schema)));
        return new Uri("urn:anyinfer:schema:" + Convert.ToHexString(hash).ToLowerInvariant());
    }

    private static Uri CanonicalUri(JsonValue document, Uri requested)
    {
        if (document is JsonObject { } obj
            && obj.TryGetValue("$id", out var id)
            && id is JsonString { Value: { Length: > 0 } text }
            && Uri.TryCreate(requested, text, out var resolved)
            && resolved.IsAbsoluteUri)
        {
            return WithoutFragment(resolved);
        }

        return requested;
    }

    private static Uri WithoutFragment(Uri uri) => new UriBuilder(uri) { Fragment = string.Empty }.Uri;

    private static JsonElement Parse(string json)
    {
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }

    private static IEnumerable<EvaluationResults> Flatten(EvaluationResults root)
    {
        yield return root;
        foreach (var detail in root.Details ?? [])
        {
            foreach (var nested in Flatten(detail))
            {
                yield return nested;
            }
        }
    }

    private static ReferenceFailure Conflict(Uri resourceUri, string message) =>
        new(resourceUri, null, new InvalidOperationException(message));

    internal sealed class MissingResource(Uri uri) : Exception
    {
        internal Uri Uri { get; } = uri;
    }

    internal sealed class ReferenceFailure(Uri resourceUri, string? fragment, Exception nativeInner)
        : Exception(nativeInner.Message, nativeInner)
    {
        internal Uri ResourceUri { get; } = resourceUri;
        internal string? Fragment { get; } = fragment;
        internal Exception NativeInner { get; } = nativeInner;
    }

    internal sealed class EvaluationFailure(Exception nativeInner)
        : Exception(nativeInner.Message, nativeInner)
    {
        internal Exception NativeInner { get; } = nativeInner;
    }

    private sealed class PlannedDocument(Uri canonicalUri, JsonElement source, string content, bool isMeta)
    {
        internal Uri CanonicalUri { get; } = canonicalUri;
        internal JsonElement Source { get; } = source;
        internal string Content { get; } = content;
        internal bool IsMeta { get; } = isMeta;
        internal DecoratedDocument? Document { get; set; }
    }

    private sealed record DocumentCandidate(Uri RequestedUri, Uri CanonicalUri, JsonElement Source, string Content, bool IsMeta)
    {
        internal static DocumentCandidate FromJson(Uri requestedUri, JsonValue value)
        {
            var source = Parse(JsonWriter.WriteModern(value));
            return new DocumentCandidate(
                requestedUri,
                ModernSchemaEngine.CanonicalUri(value, requestedUri),
                source,
                JsonWriter.WriteCanonicalModern(value),
                false);
        }
    }

    private sealed record BoundDocuments(PlannedDocument Root, PlannedDocument SelectedMeta);

    private sealed class DecoratedDocument : IBaseDocument
    {
        private readonly JsonElementBaseDocument _inner;
        private readonly TimeSpan _timeout;
        private readonly HashSet<JsonSchemaNode> _owned = new(ReferenceEqualityComparer.Instance);

        internal DecoratedDocument(JsonElement source, Uri baseUri, TimeSpan timeout)
        {
            _inner = new JsonElementBaseDocument(source, baseUri);
            _timeout = timeout;
        }

        public Uri BaseUri => _inner.BaseUri;

        public JsonSchemaNode? FindSubschema(JsonPointer pointer, BuildContext context)
        {
            var node = _inner.FindSubschema(pointer, context);
            if (node is not null)
            {
                Decorate(node);
            }

            return node;
        }

        internal bool Owns(JsonSchemaNode node) => _owned.Contains(node);

        private void Decorate(JsonSchemaNode node)
        {
            if (!_owned.Add(node)) return;
            foreach (var keyword in node.Keywords)
            {
                if (keyword.Handler is PatternKeyword && keyword.Value is Regex pattern)
                {
                    keyword.Value = new Regex(pattern.ToString(), pattern.Options, _timeout);
                }
                else if (keyword.Handler is PatternPropertiesKeyword
                    && keyword.Value is Dictionary<string, Regex> patterns)
                {
                    keyword.Value = patterns.ToDictionary(
                        static item => item.Key,
                        item => new Regex(item.Value.ToString(), item.Value.Options, _timeout));
                }

                if (keyword.Handler is RefKeyword || keyword.Handler.Name == "$dynamicRef") continue;
                foreach (var child in keyword.Subschemas)
                {
                    Decorate(child);
                }
            }
        }
    }
}
