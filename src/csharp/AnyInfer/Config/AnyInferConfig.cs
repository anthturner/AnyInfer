using System.Collections.ObjectModel;
using AnyInfer.Capabilities;
using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using System.Numerics;
using System.Text;

namespace AnyInfer.Config;

/// <summary>Inert, validated version 1 configuration shared by C# AnyInfer integrations.</summary>
/// <remarks>
/// <para>
/// This reader and writer implement a bounded subset of the shared JSON configuration format. A
/// document must be a JSON object of at most <see cref="MaximumBytes"/> UTF-8 bytes whose optional
/// <c>format_version</c> is 1. The root may contain <c>providers</c>, <c>default_route</c>,
/// <c>operation_routes</c> (only <c>embedding</c> and <c>rerank</c>), <c>cache</c>, and <c>repair</c>
/// (only <c>max_attempts</c>), plus <c>_comment</c> and the demo application's UI keys, which are
/// accepted and ignored. The <c>context</c>, <c>history</c>, <c>observers</c>, <c>arena</c>,
/// <c>arenas</c>, and <c>mcp</c> blocks are rejected as unimplemented, and any other key is rejected.
/// </para>
/// <para>
/// Each provider entry needs an <c>id</c>. An entry whose boolean <c>enabled</c> is
/// <see langword="false"/> is skipped without validating its other keys. An enabled entry may also set
/// <c>adapter</c> (or its legacy spelling <c>provider_id</c>), an <c>alias</c> that restates the id,
/// <c>base_url</c>, <c>api_key</c>, <c>api_version</c>, <c>headers</c>, <c>options</c>,
/// <c>timeout_s</c> (a positive number, 120 when omitted), <c>limits</c>, <c>proxy</c>, <c>verify</c>,
/// and <c>client_cert</c>, and the provider's declared setup fields directly or under <c>values</c>.
/// Instance identifiers must be unique.
/// </para>
/// <para>
/// Loading resolves no credential, constructs no adapter, and opens no CA-bundle or certificate file;
/// an <c>api_key</c> is only checked with <see cref="ResolverChain.Handles"/>, so a reference whose
/// scheme no resolver handles fails at load. Invalid content fails with a
/// <see cref="ConfigException"/> whose message names the source.
/// </para>
/// </remarks>
public sealed class AnyInferConfig
{
    /// <summary>The only configuration format version this reader and writer accept.</summary>
    public const int FormatVersion1 = 1;

    /// <summary>The largest configuration document, in UTF-8 bytes (1 MiB), that <see cref="Load"/> and <see cref="Loads"/> accept.</summary>
    public const int MaximumBytes = 1024 * 1024;

    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly HashSet<string> RootKeys = new(StringComparer.Ordinal)
    {
        "_comment", "format_version", "providers", "default_route", "repair",
        "operation_routes", "context", "history", "cache", "observers", "arena", "arenas", "mcp",
        "targets", "system_prompt", "theme", "context_window_tokens", "ignore_runtime_hardware_constraints",
    };
    private static readonly HashSet<string> InertDemoKeys = new(StringComparer.Ordinal)
    {
        "targets", "system_prompt", "theme", "context_window_tokens", "ignore_runtime_hardware_constraints",
    };
    private static readonly HashSet<string> UnimplementedKeys = new(StringComparer.Ordinal)
    {
        "context", "history", "observers", "arena", "arenas", "mcp",
    };
    private static readonly HashSet<string> IdentityKeys = new(StringComparer.Ordinal) { "id", "adapter", "provider_id", "alias", "enabled" };
    private static readonly HashSet<string> SettingKeys = new(StringComparer.Ordinal)
    {
        "base_url", "api_key", "api_version", "headers", "options", "timeout_s", "values", "limits", "proxy", "verify", "client_cert",
    };
    private static readonly HashSet<string> DirectKeys = new(StringComparer.Ordinal) { "base_url", "api_key", "api_version" };

    /// <summary>Creates an immutable configuration without resolving credentials or constructing adapters.</summary>
    /// <param name="providers">Provider settings in preference order, copied; <see langword="null"/> for none. Instance identifiers are not checked for uniqueness here; the loader and client construction check them.</param>
    /// <param name="route">Default generation route, or <see langword="null"/> for none.</param>
    /// <param name="repair">Default schema-repair budget, or <see langword="null"/> for no repair.</param>
    /// <param name="formatVersion">Configuration format version; only <see cref="FormatVersion1"/> is accepted.</param>
    /// <param name="cache">Prompt-cache placement policy, or <see langword="null"/> for none.</param>
    /// <param name="operationRoutes">Default routes for <see cref="InferenceOperation.Embedding"/> and <see cref="InferenceOperation.Rerank"/> only, copied; <see langword="null"/> for none.</param>
    /// <exception cref="ConfigException"><paramref name="formatVersion"/> is unsupported, or <paramref name="operationRoutes"/> names another operation or holds a <see langword="null"/> route.</exception>
    /// <exception cref="ArgumentException"><paramref name="providers"/> contains a <see langword="null"/> element.</exception>
    public AnyInferConfig(
        IEnumerable<ProviderSettings>? providers = null,
        Route? route = null,
        Repair? repair = null,
        int formatVersion = FormatVersion1,
        CachePolicy? cache = null,
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes = null)
    {
        if (formatVersion != FormatVersion1)
        {
            throw new ConfigException("The configuration format version is unsupported.");
        }

        Providers = Array.AsReadOnly((providers ?? []).Select(static provider => provider ?? throw new ArgumentException("Providers cannot contain null references.")).ToArray());
        Route = route;
        Repair = repair;
        FormatVersion = formatVersion;
        Cache = cache;
        OperationRoutes = CopyOperationRoutes(operationRoutes);
    }

    /// <summary>Gets provider settings in declaration order.</summary>
    public IReadOnlyList<ProviderSettings> Providers { get; }

    /// <summary>Gets the optional default generation route.</summary>
    public Route? Route { get; }

    /// <summary>Gets the optional schema-repair budget.</summary>
    public Repair? Repair { get; }

    /// <summary>Gets the parsed format version.</summary>
    public int FormatVersion { get; }

    /// <summary>Gets the optional prompt-cache placement policy declared by configuration.</summary>
    public CachePolicy? Cache { get; }

    /// <summary>Gets copied routes declared for retrieval operations.</summary>
    public IReadOnlyDictionary<InferenceOperation, Route> OperationRoutes { get; }

    /// <summary>Loads and validates a UTF-8 configuration document from an explicit path.</summary>
    /// <param name="path">Path of the configuration file; no default location is searched. The path appears in error messages.</param>
    /// <param name="registry">Provider registry that validates adapter names, setup fields, required fields, and connection-setting support; <see langword="null"/> uses <see cref="ProviderRegistry.CreateDefault"/>.</param>
    /// <param name="resolver">Credential resolver chain that must accept each <c>api_key</c> through <see cref="ResolverChain.Handles"/>; nothing is resolved. <see langword="null"/> uses <see cref="ResolverChain.CreateDefault"/>.</param>
    /// <returns>The validated configuration.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="path"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="path"/> is empty or whitespace.</exception>
    /// <exception cref="ConfigException">The file cannot be read, exceeds <see cref="MaximumBytes"/>, is not valid UTF-8 JSON, or does not describe a valid version 1 configuration.</exception>
    public static AnyInferConfig Load(string path, ProviderRegistry? registry = null, ResolverChain? resolver = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        byte[] bytes;
        try
        {
            bytes = ReadBoundedFile(path);
        }
        catch (ConfigException)
        {
            throw;
        }
        catch (IOException exception)
        {
            throw Fail(path, "Configuration file cannot be read.", exception);
        }
        catch (UnauthorizedAccessException exception)
        {
            throw Fail(path, "Configuration file cannot be read.", exception);
        }
        catch (ArgumentException exception)
        {
            throw Fail(path, "Configuration file path is invalid.", exception);
        }

        JsonValue value;
        try
        {
            value = JsonReader.Read(bytes);
        }
        catch (FormatException exception)
        {
            throw Fail(path, "Configuration is not valid UTF-8 JSON.", exception);
        }

        return Parse(value, path, registry, resolver);
    }

    /// <summary>Loads and validates a configuration JSON string without resolving credentials or constructing adapters.</summary>
    /// <param name="text">Configuration JSON text, at most <see cref="MaximumBytes"/> when encoded as UTF-8.</param>
    /// <param name="registry">Provider registry that validates adapter names, setup fields, required fields, and connection-setting support; <see langword="null"/> uses <see cref="ProviderRegistry.CreateDefault"/>.</param>
    /// <param name="resolver">Credential resolver chain that must accept each <c>api_key</c> through <see cref="ResolverChain.Handles"/>; nothing is resolved. <see langword="null"/> uses <see cref="ResolverChain.CreateDefault"/>.</param>
    /// <param name="source">Label that names the document in error messages; <c>&lt;string&gt;</c> by default.</param>
    /// <returns>The validated configuration.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> or <paramref name="source"/> is <see langword="null"/>.</exception>
    /// <exception cref="ConfigException"><paramref name="text"/> exceeds <see cref="MaximumBytes"/>, is not valid UTF-8 JSON, or does not describe a valid version 1 configuration.</exception>
    public static AnyInferConfig Loads(string text, ProviderRegistry? registry = null, ResolverChain? resolver = null, string source = "<string>")
    {
        ArgumentNullException.ThrowIfNull(text);
        ArgumentNullException.ThrowIfNull(source);
        try
        {
            if (StrictUtf8.GetByteCount(text) > MaximumBytes)
            {
                throw Fail(source, $"Configuration exceeds the {MaximumBytes}-byte limit.");
            }

            var value = JsonReader.Read(text);
            return Parse(value, source, registry, resolver);
        }
        catch (ConfigException)
        {
            throw;
        }
        catch (EncoderFallbackException exception)
        {
            throw Fail(source, "Configuration is not valid UTF-8.", exception);
        }
        catch (FormatException exception)
        {
            throw Fail(source, "Configuration is not valid JSON.", exception);
        }
    }

    /// <summary>Renders this configuration as canonical two-space JSON without resolving credentials.</summary>
    /// <remarks>
    /// Values are written exactly as configured. A credential reference such as <c>env://NAME</c> stays
    /// a reference, but a literal <c>api_key</c>, header values, options, the proxy URI with any user
    /// name and password, the <c>verify</c> CA-bundle path, and the <c>client_cert</c> paths and password
    /// are all written as literal text, so protect the output. A 120-second timeout, default values
    /// inside the <c>limits</c> and <c>cache</c> blocks, transport handlers, and ignored demo keys are
    /// not written; a block whose values are all defaults is written as an empty object.
    /// </remarks>
    /// <param name="comments">Whether to add a root <c>_comment</c> string that recommends credential references; the loader accepts and ignores it.</param>
    /// <returns>JSON with sorted keys, two-space indentation, non-ASCII characters escaped, and a trailing newline.</returns>
    /// <exception cref="ConfigException">The default route or an operation route uses retry, health, or context-window settings that format version 1 cannot express, or a value cannot be serialized as JSON.</exception>
    public string Dumps(bool comments = false)
    {
        try
        {
            var properties = new List<JsonProperty>();
            if (comments)
            {
                properties.Add(new JsonProperty("_comment", new JsonString("AnyInfer configuration. Prefer credential references and review literal credentials before committing.")));
            }

            properties.Add(new JsonProperty("format_version", new JsonInteger(FormatVersion)));
            if (Providers.Count != 0)
            {
                properties.Add(new JsonProperty("providers", new JsonArray(Providers.Select(ProviderJson))));
            }

            if (Route is not null)
            {
                EnsureDefaultRouteCanSerialize(Route);
                properties.Add(new JsonProperty("default_route", new JsonArray(Route.Targets.Select(static target => new JsonString(target)))));
            }

            if (Cache is not null)
            {
                properties.Add(new JsonProperty("cache", CacheJson(Cache)));
            }

            if (OperationRoutes.Count != 0)
            {
                var operationRoutes = new List<JsonProperty>();
                foreach (var operation in new[] { InferenceOperation.Embedding, InferenceOperation.Rerank })
                {
                    if (!OperationRoutes.TryGetValue(operation, out var route))
                    {
                        continue;
                    }

                    EnsureDefaultRouteCanSerialize(route);
                    operationRoutes.Add(new JsonProperty(
                        OperationRouteName(operation),
                        new JsonArray(route.Targets.Select(static target => new JsonString(target)))));
                }

                properties.Add(new JsonProperty("operation_routes", new JsonObject(operationRoutes)));
            }

            if (Repair is not null)
            {
                properties.Add(new JsonProperty("repair", new JsonObject([new JsonProperty("max_attempts", new JsonInteger(Repair.MaxAttempts))])));
            }

            return JsonWriter.WriteCanonical(new JsonObject(properties)) + "\n";
        }
        catch (ConfigException)
        {
            throw;
        }
        catch (ArgumentException exception)
        {
            throw new ConfigException("Configuration cannot be serialized as JSON.", detail: exception.Message, nativeInner: exception);
        }
    }

    /// <summary>Writes this configuration to a new file, or over an existing one only when overwrite is explicit.</summary>
    /// <remarks>
    /// The text is <see cref="Dumps"/> with <c>comments</c> set to <see langword="true"/>, written as
    /// UTF-8 without a byte-order mark. It contains literal configured values, so protect the file. The
    /// write is not staged through a temporary file, so an interrupted write can leave a partial file.
    /// </remarks>
    /// <param name="path">Destination file path; its parent directory must already exist.</param>
    /// <param name="force"><see langword="false"/> (the default) to create the file exclusively and fail if it exists; <see langword="true"/> to replace an existing file.</param>
    /// <exception cref="ArgumentNullException"><paramref name="path"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="path"/> is empty or whitespace.</exception>
    /// <exception cref="ConfigException">The parent directory does not exist, the file exists and <paramref name="force"/> is <see langword="false"/>, the file cannot be written, the path is invalid, or <see cref="Dumps"/> fails.</exception>
    public void Dump(string path, bool force = false)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var text = Dumps(comments: true);
        try
        {
            var destination = Path.GetFullPath(path);
            var parent = Path.GetDirectoryName(destination);
            if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent))
            {
                throw new ConfigException("Configuration parent directory does not exist.");
            }

            using var stream = new FileStream(destination, force ? FileMode.Create : FileMode.CreateNew, FileAccess.Write, FileShare.None);
            using var writer = new StreamWriter(stream, new UTF8Encoding(false));
            writer.Write(text);
        }
        catch (IOException exception)
        {
            throw new ConfigException("Configuration file cannot be written.", nativeInner: exception);
        }
        catch (UnauthorizedAccessException exception)
        {
            throw new ConfigException("Configuration file cannot be written.", nativeInner: exception);
        }
        catch (ArgumentException exception)
        {
            throw new ConfigException("Configuration file path is invalid.", nativeInner: exception);
        }
    }

    /// <summary>Returns a credential-safe configuration summary.</summary>
    /// <returns>The provider count and whether a default route is configured, such as <c>AnyInferConfig(Providers=2, Route=configured)</c>.</returns>
    public override string ToString() => $"AnyInferConfig(Providers={Providers.Count}, Route={(Route is null ? "none" : "configured")})";

    private static byte[] ReadBoundedFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, bufferSize: 4096, FileOptions.SequentialScan);
        var bytes = new byte[MaximumBytes + 1];
        var offset = 0;
        while (offset < bytes.Length)
        {
            var read = stream.Read(bytes, offset, bytes.Length - offset);
            if (read == 0)
            {
                break;
            }

            offset += read;
        }

        if (offset > MaximumBytes)
        {
            throw Fail(path, $"Configuration exceeds the {MaximumBytes}-byte limit.");
        }

        return bytes[..offset];
    }

    private static AnyInferConfig Parse(JsonValue value, string source, ProviderRegistry? registry, ResolverChain? resolver)
    {
        if (value is not JsonObject root)
        {
            throw Fail(source, "Configuration document must be an object.");
        }

        var unknown = root.Properties.Select(static property => property.Name).Where(name => !RootKeys.Contains(name)).ToArray();
        if (unknown.Length != 0)
        {
            throw Fail(source, $"Configuration has unknown key(s): {string.Join(", ", unknown.OrderBy(static name => name, StringComparer.Ordinal))}.");
        }

        foreach (var key in UnimplementedKeys)
        {
            if (root.TryGetValue(key, out _))
            {
                throw Fail(source, $"Configuration key '{key}' is not implemented in this SDK phase.");
            }
        }

        var version = root.TryGetValue("format_version", out var rawVersion) ? RequiredInteger(rawVersion, source, "format_version") : FormatVersion1;
        if (version != FormatVersion1)
        {
            throw Fail(source, "Configuration format_version is unsupported.");
        }

        var activeRegistry = registry ?? ProviderRegistry.CreateDefault();
        var activeResolver = resolver ?? ResolverChain.CreateDefault();
        var providers = ParseProviders(GetOrDefault(root, "providers", new JsonArray([])), source, activeRegistry, activeResolver);
        var route = ParseRoute(GetOrDefault(root, "default_route", JsonNull.Instance), source);
        var repair = ParseRepair(GetOrDefault(root, "repair", JsonNull.Instance), source);
        var cache = ParseCache(GetOrDefault(root, "cache", JsonNull.Instance), source);
        var operationRoutes = ParseOperationRoutes(GetOrDefault(root, "operation_routes", JsonNull.Instance), source);
        return new AnyInferConfig(providers, route, repair, version, cache, operationRoutes);
    }

    private static IReadOnlyList<ProviderSettings> ParseProviders(JsonValue value, string source, ProviderRegistry registry, ResolverChain resolver)
    {
        if (value is not JsonArray array)
        {
            throw Fail(source, "providers must be an array.");
        }

        var providers = new List<ProviderSettings>();
        var identities = new HashSet<string>(StringComparer.Ordinal);
        for (var index = 0; index < array.Items.Count; index++)
        {
            if (array.Items[index] is not JsonObject provider)
            {
                throw Fail(source, $"providers[{index}] must be an object.");
            }

            var settings = ParseProvider(provider, source, $"providers[{index}]", registry, resolver);
            if (settings is null)
            {
                continue;
            }

            if (!identities.Add(settings.InstanceId))
            {
                throw Fail(source, "Provider instance IDs must be unique.");
            }

            providers.Add(settings);
        }

        return providers;
    }

    private static ProviderSettings? ParseProvider(JsonObject raw, string source, string location, ProviderRegistry registry, ResolverChain resolver)
    {
        if (raw.TryGetValue("enabled", out var enabledValue))
        {
            if (enabledValue is not JsonBoolean enabled)
            {
                throw Fail(source, $"{location}.enabled must be a boolean.");
            }

            if (!enabled.Value)
            {
                return null;
            }
        }

        var instance = RequiredNonBlankString(GetOrDefault(raw, "id", JsonNull.Instance), source, $"{location}.id");
        var adapter = OptionalTruthyString(raw, "adapter", source, location);
        var legacy = OptionalTruthyString(raw, "provider_id", source, location);
        if (adapter is not null && legacy is not null && !string.Equals(ProviderRegistry.NormalizeProviderId(adapter), ProviderRegistry.NormalizeProviderId(legacy), StringComparison.Ordinal))
        {
            throw Fail(source, $"{location}.adapter and provider_id disagree.");
        }

        var engine = adapter ?? legacy ?? instance;
        var descriptor = GetDescriptor(registry, engine, source, location);
        var instanceId = ProviderRegistry.NormalizeProviderId(instance);
        if (raw.TryGetValue("alias", out var aliasValue))
        {
            if (aliasValue is not JsonNull)
            {
                var alias = RequiredNonBlankString(aliasValue, source, $"{location}.alias");
                if (!string.Equals(ProviderRegistry.NormalizeProviderId(alias), instanceId, StringComparison.Ordinal))
                {
                    throw Fail(source, $"{location}.alias must normalize to id.");
                }
            }
        }

        var declared = descriptor.Setup.Fields.Select(static field => field.Key).ToHashSet(StringComparer.Ordinal);
        var allowed = new HashSet<string>(IdentityKeys, StringComparer.Ordinal);
        allowed.UnionWith(SettingKeys);
        allowed.UnionWith(declared);
        var unknown = raw.Properties.Select(static property => property.Name).Where(name => !allowed.Contains(name)).ToArray();
        if (unknown.Length != 0)
        {
            throw Fail(source, $"{location} has unknown key(s): {string.Join(", ", unknown)}.");
        }

        var values = NullableObject(raw, "values", source, location);
        var options = NullableObject(raw, "options", source, location) ?? new JsonObject([]);
        var valueUnknown = values?.Properties.Select(static property => property.Name).Where(name => !declared.Contains(name) && !DirectKeys.Contains(name)).ToArray() ?? [];
        if (valueUnknown.Length != 0)
        {
            throw Fail(source, $"{location}.values has unknown key(s): {string.Join(", ", valueUnknown)}.");
        }

        var baseUrl = DirectString(raw, values, "base_url", source, location);
        var apiKey = DirectString(raw, values, "api_key", source, location);
        var apiVersion = DirectString(raw, values, "api_version", source, location);
        if (apiKey is not null && !resolver.Handles(apiKey))
        {
            throw Fail(source, $"{location}.api_key uses an unhandled credential reference.");
        }

        var mergedOptions = options;
        foreach (var field in declared.Where(field => !DirectKeys.Contains(field)))
        {
            var candidate = Select(raw, values, field);
            if (candidate is not null && candidate is not JsonNull && !mergedOptions.TryGetValue(field, out _))
            {
                mergedOptions = new JsonObject(mergedOptions.Properties.Append(new JsonProperty(field, candidate)));
            }
        }

        var headers = ParseHeaders(GetOrDefault(raw, "headers", new JsonObject([])), source, location);
        var timeout = ParseTimeout(GetOrDefault(raw, "timeout_s", new JsonNumber(120)), source, location);
        var limits = ParseLimits(GetOrDefault(raw, "limits", JsonNull.Instance), source, location);
        var proxy = ParseProxy(raw, source, location);
        var verify = ParseVerify(raw, source, location);
        var clientCertificate = ParseClientCertificate(raw, source, location);
        if (!descriptor.HonorsConnectionSettings && (proxy is not null || verify is not null || clientCertificate is not null))
        {
            throw Fail(source, $"{location} does not support connection settings.");
        }
        if (descriptor.RequiresBaseUrl && string.IsNullOrEmpty(baseUrl) && string.IsNullOrEmpty(descriptor.DefaultBaseUrl))
        {
            throw Fail(source, $"{location} requires base_url.");
        }

        foreach (var field in descriptor.Setup.Fields.Where(static field => field.Required))
        {
            var configured = field.Key switch
            {
                "base_url" => baseUrl ?? descriptor.DefaultBaseUrl,
                "api_key" => apiKey,
                _ => mergedOptions.TryGetValue(field.Key, out var option) && option is not JsonNull ? JsonWriter.Write(option) : null,
            };
            if (string.IsNullOrEmpty(configured))
            {
                throw Fail(source, $"{location} is missing required setup field '{field.Key}'.");
            }
        }

        return new ProviderSettings(
            ProviderRegistry.NormalizeProviderId(engine),
            baseUrl ?? descriptor.DefaultBaseUrl,
            apiKey,
            apiVersion,
            headers,
            mergedOptions.Properties.Count == 0 ? null : mergedOptions,
            timeout,
            alias: instanceId == ProviderRegistry.NormalizeProviderId(engine) ? null : instanceId,
            limits: limits,
            proxy: proxy,
            verify: verify,
            clientCertificate: clientCertificate);
    }

    private static CachePolicy? ParseCache(JsonValue value, string source)
    {
        if (value is JsonNull)
        {
            return null;
        }

        if (value is not JsonObject raw)
        {
            throw Fail(source, "cache must be an object.");
        }

        var known = new HashSet<string>(StringComparer.Ordinal)
        {
            "mode", "min_segment_tokens", "max_marks", "include_tools", "include_system",
        };
        RejectUnknown(raw, known, source, "cache");
        var mode = raw.TryGetValue("mode", out var rawMode)
            ? ParseCacheMode(rawMode, source)
            : CacheMode.Auto;
        var minSegmentTokens = raw.TryGetValue("min_segment_tokens", out var rawMinimum)
            ? RequiredLong(rawMinimum, source, "cache.min_segment_tokens")
            : 1024;
        var maxMarks = raw.TryGetValue("max_marks", out var rawMarks)
            ? RequiredInteger(rawMarks, source, "cache.max_marks")
            : 4;
        var includeTools = raw.TryGetValue("include_tools", out var rawTools)
            ? RequiredBoolean(rawTools, source, "cache.include_tools")
            : true;
        var includeSystem = raw.TryGetValue("include_system", out var rawSystem)
            ? RequiredBoolean(rawSystem, source, "cache.include_system")
            : true;
        try
        {
            return new CachePolicy(mode, minSegmentTokens, maxMarks, includeTools, includeSystem);
        }
        catch (ArgumentOutOfRangeException exception)
        {
            throw Fail(source, "cache is invalid.", exception);
        }
    }

    private static RateLimits? ParseLimits(JsonValue value, string source, string location)
    {
        if (value is JsonNull)
        {
            return null;
        }

        if (value is not JsonObject raw)
        {
            throw Fail(source, $"{location}.limits must be an object.");
        }

        var known = new HashSet<string>(StringComparer.Ordinal)
        {
            "max_concurrent", "requests_per_minute", "min_interval_s", "respect_headers", "reserve_fraction",
        };
        RejectUnknown(raw, known, source, $"{location}.limits");
        int? maxConcurrent = raw.TryGetValue("max_concurrent", out var rawConcurrency)
            ? RequiredInteger(rawConcurrency, source, $"{location}.limits.max_concurrent")
            : null;
        double? requestsPerMinute = raw.TryGetValue("requests_per_minute", out var rawRate)
            ? RequiredFiniteNumber(rawRate, source, $"{location}.limits.requests_per_minute")
            : null;
        var minInterval = raw.TryGetValue("min_interval_s", out var rawInterval)
            ? RequiredFiniteNumber(rawInterval, source, $"{location}.limits.min_interval_s")
            : 0d;
        var respectHeaders = raw.TryGetValue("respect_headers", out var rawHeaders)
            ? RequiredBoolean(rawHeaders, source, $"{location}.limits.respect_headers")
            : true;
        var reserveFraction = raw.TryGetValue("reserve_fraction", out var rawReserve)
            ? RequiredFiniteNumber(rawReserve, source, $"{location}.limits.reserve_fraction")
            : 0d;
        try
        {
            return new RateLimits(maxConcurrent, requestsPerMinute, minInterval, respectHeaders, reserveFraction);
        }
        catch (ArgumentOutOfRangeException exception)
        {
            throw Fail(source, $"{location}.limits is invalid.", exception);
        }
    }

    private static Route? ParseRoute(JsonValue value, string source)
    {
        if (value is JsonNull)
        {
            return null;
        }

        if (value is not JsonArray array)
        {
            throw Fail(source, "default_route must be an array of target strings.");
        }

        if (array.Items.Count == 0)
        {
            return null;
        }

        return new Route(array.Items.Select((item, index) => RequiredNonBlankString(item, source, $"default_route[{index}]")));
    }

    private static IReadOnlyDictionary<InferenceOperation, Route> ParseOperationRoutes(JsonValue value, string source)
    {
        if (value is JsonNull)
        {
            return new Dictionary<InferenceOperation, Route>();
        }

        if (value is not JsonObject routes)
        {
            throw Fail(source, "operation_routes must be an object.");
        }

        var parsed = new Dictionary<InferenceOperation, Route>();
        foreach (var property in routes.Properties)
        {
            var operation = property.Name switch
            {
                "embedding" => InferenceOperation.Embedding,
                "rerank" => InferenceOperation.Rerank,
                _ => throw Fail(source, $"operation_routes has unsupported key '{property.Name}'."),
            };
            if (property.Value is not JsonArray targets || targets.Items.Count == 0)
            {
                throw Fail(source, $"operation_routes.{property.Name} must be a nonempty array of target strings.");
            }

            if (!parsed.TryAdd(operation, new Route(targets.Items.Select((item, index) =>
                RequiredNonBlankString(item, source, $"operation_routes.{property.Name}[{index}]")))))
            {
                throw Fail(source, $"operation_routes has duplicate key '{property.Name}'.");
            }
        }

        return parsed;
    }

    private static Repair? ParseRepair(JsonValue value, string source)
    {
        if (value is JsonNull)
        {
            return null;
        }

        if (value is not JsonObject raw || raw.Properties.Any(static property => property.Name != "max_attempts"))
        {
            throw Fail(source, "repair must be an object containing only max_attempts.");
        }

        var attempts = raw.TryGetValue("max_attempts", out var valueAttempts) ? RequiredInteger(valueAttempts, source, "repair.max_attempts") : 1;
        if (attempts < 0)
        {
            throw Fail(source, "repair.max_attempts must be nonnegative.");
        }

        return new Repair(attempts);
    }

    private static JsonObject ProviderJson(ProviderSettings settings)
    {
        var properties = new List<JsonProperty> { new("id", new JsonString(settings.InstanceId)) };
        if (!string.Equals(settings.InstanceId, settings.ProviderId, StringComparison.Ordinal))
        {
            properties.Add(new JsonProperty("adapter", new JsonString(settings.ProviderId)));
        }

        AddString(properties, "base_url", settings.BaseUrl);
        AddString(properties, "api_key", settings.ApiKey);
        AddString(properties, "api_version", settings.ApiVersion);
        if (settings.Headers.Count != 0)
        {
            properties.Add(new JsonProperty("headers", new JsonObject(settings.Headers.Select(static pair => new JsonProperty(pair.Key, new JsonString(pair.Value))))));
        }

        if (settings.Options is not null && settings.Options.Properties.Count != 0)
        {
            properties.Add(new JsonProperty("options", settings.Options));
        }

        if (settings.TimeoutS != 120)
        {
            properties.Add(new JsonProperty("timeout_s", new JsonNumber(settings.TimeoutS)));
        }

        if (settings.Limits is not null)
        {
            properties.Add(new JsonProperty("limits", LimitsJson(settings.Limits)));
        }

        if (settings.Proxy is not null)
        {
            properties.Add(new JsonProperty("proxy", new JsonString(settings.Proxy.ConfigurationValue)));
        }

        if (settings.Verify is not null)
        {
            properties.Add(new JsonProperty("verify", settings.Verify.PemBundlePath is null
                ? new JsonBoolean(false)
                : new JsonString(settings.Verify.PemBundlePath)));
        }

        if (settings.ClientCertificate is { } certificate)
        {
            properties.Add(new JsonProperty("client_cert", certificate.PrivateKeyPath is null
                ? new JsonString(certificate.CertificatePath)
                : new JsonArray(certificate.Password is null
                    ? [new JsonString(certificate.CertificatePath), new JsonString(certificate.PrivateKeyPath)]
                    : [new JsonString(certificate.CertificatePath), new JsonString(certificate.PrivateKeyPath), new JsonString(certificate.Password)])));
        }

        return new JsonObject(properties);
    }

    private static JsonObject CacheJson(CachePolicy cache)
    {
        var defaults = new CachePolicy();
        var properties = new List<JsonProperty>();
        if (cache.Mode != defaults.Mode)
        {
            properties.Add(new JsonProperty("mode", new JsonString(CacheModeJson(cache.Mode))));
        }

        if (cache.MinSegmentTokens != defaults.MinSegmentTokens)
        {
            properties.Add(new JsonProperty("min_segment_tokens", new JsonInteger(cache.MinSegmentTokens)));
        }

        if (cache.MaxMarks != defaults.MaxMarks)
        {
            properties.Add(new JsonProperty("max_marks", new JsonInteger(cache.MaxMarks)));
        }

        if (cache.IncludeTools != defaults.IncludeTools)
        {
            properties.Add(new JsonProperty("include_tools", new JsonBoolean(cache.IncludeTools)));
        }

        if (cache.IncludeSystem != defaults.IncludeSystem)
        {
            properties.Add(new JsonProperty("include_system", new JsonBoolean(cache.IncludeSystem)));
        }

        return new JsonObject(properties);
    }

    private static JsonObject LimitsJson(RateLimits limits)
    {
        var defaults = new RateLimits();
        var properties = new List<JsonProperty>();
        if (limits.MaxConcurrent is { } concurrency)
        {
            properties.Add(new JsonProperty("max_concurrent", new JsonInteger(concurrency)));
        }

        if (limits.RequestsPerMinute is { } rate)
        {
            properties.Add(new JsonProperty("requests_per_minute", new JsonNumber(rate)));
        }

        if (limits.MinIntervalS != defaults.MinIntervalS)
        {
            properties.Add(new JsonProperty("min_interval_s", new JsonNumber(limits.MinIntervalS)));
        }

        if (limits.RespectHeaders != defaults.RespectHeaders)
        {
            properties.Add(new JsonProperty("respect_headers", new JsonBoolean(limits.RespectHeaders)));
        }

        if (limits.ReserveFraction != defaults.ReserveFraction)
        {
            properties.Add(new JsonProperty("reserve_fraction", new JsonNumber(limits.ReserveFraction)));
        }

        return new JsonObject(properties);
    }

    private static void AddString(ICollection<JsonProperty> properties, string name, string? value)
    {
        if (value is not null)
        {
            properties.Add(new JsonProperty(name, new JsonString(value)));
        }
    }

    private static ProviderDescriptor GetDescriptor(ProviderRegistry registry, string engine, string source, string location)
    {
        try { return registry.Get(engine); }
        catch (ProviderException exception) { throw Fail(source, $"{location} names an unknown provider.", exception); }
    }

    private static JsonObject? NullableObject(JsonObject raw, string name, string source, string location)
    {
        if (!raw.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        return value as JsonObject ?? throw Fail(source, $"{location}.{name} must be an object.");
    }

    private static JsonValue? Select(JsonObject raw, JsonObject? values, string name)
        => raw.TryGetValue(name, out var direct) ? direct : values is not null && values.TryGetValue(name, out var nested) ? nested : null;

    private static string? DirectString(JsonObject raw, JsonObject? values, string name, string source, string location)
    {
        var value = Select(raw, values, name);
        if (value is null || value is JsonNull)
        {
            return null;
        }

        if (value is not JsonString text)
        {
            throw Fail(source, $"{location}.{name} must be a string.");
        }

        return text.Value.Length == 0 ? null : text.Value;
    }

    private static IReadOnlyDictionary<string, string> ParseHeaders(JsonValue value, string source, string location)
    {
        if (value is JsonNull)
        {
            return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }

        if (value is not JsonObject objectValue)
        {
            throw Fail(source, $"{location}.headers must be an object.");
        }

        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in objectValue.Properties)
        {
            if (property.Name.Length == 0 || property.Value is not JsonString text || !result.TryAdd(property.Name, text.Value))
            {
                throw Fail(source, $"{location}.headers must map distinct nonempty strings to strings.");
            }
        }

        return result;
    }

    private static double ParseTimeout(JsonValue value, string source, string location)
    {
        double timeout = value switch
        {
            JsonInteger integer => (double)integer.Value,
            JsonNumber number => number.Value,
            _ => double.NaN,
        };
        if (!double.IsFinite(timeout) || timeout <= 0)
        {
            throw Fail(source, $"{location}.timeout_s must be a positive finite number.");
        }

        return timeout;
    }

    private static ProviderProxy? ParseProxy(JsonObject raw, string source, string location)
    {
        if (!raw.TryGetValue("proxy", out var value) || value is JsonNull)
        {
            return null;
        }

        if (value is not JsonString text || string.IsNullOrWhiteSpace(text.Value))
        {
            throw Fail(source, $"{location}.proxy must be a nonblank string.");
        }

        try { return ProviderProxy.Parse(text.Value); }
        catch (ArgumentException exception) { throw Fail(source, $"{location}.proxy is invalid.", exception); }
    }

    private static TlsVerification? ParseVerify(JsonObject raw, string source, string location)
    {
        if (!raw.TryGetValue("verify", out var value) || value is JsonBoolean { Value: true })
        {
            return null;
        }

        if (value is JsonBoolean { Value: false })
        {
            return TlsVerification.Disabled;
        }

        if (value is JsonString text && !string.IsNullOrWhiteSpace(text.Value))
        {
            try { return TlsVerification.FromPemBundle(text.Value); }
            catch (ArgumentException exception) { throw Fail(source, $"{location}.verify is invalid.", exception); }
        }

        throw Fail(source, $"{location}.verify must be true, false, or a nonblank string.");
    }

    private static ClientCertificate? ParseClientCertificate(JsonObject raw, string source, string location)
    {
        if (!raw.TryGetValue("client_cert", out var value) || value is JsonNull)
        {
            return null;
        }

        try
        {
            return value switch
            {
                JsonString { Value: var path } when !string.IsNullOrWhiteSpace(path) => ClientCertificate.FromPemFile(path.Trim()),
                JsonArray { Items.Count: 2 } pair when pair.Items[0] is JsonString first && pair.Items[1] is JsonString second
                    && !string.IsNullOrWhiteSpace(first.Value) && !string.IsNullOrWhiteSpace(second.Value) => ClientCertificate.FromPemPair(first.Value, second.Value),
                JsonArray { Items.Count: 3 } triple when triple.Items[0] is JsonString first && triple.Items[1] is JsonString second && triple.Items[2] is JsonString password
                    && !string.IsNullOrWhiteSpace(first.Value) && !string.IsNullOrWhiteSpace(second.Value) && password.Value.Length != 0 => ClientCertificate.FromEncryptedPemPair(first.Value, second.Value, password.Value),
                _ => throw Fail(source, $"{location}.client_cert must be a nonblank string or a two/three-string array."),
            };
        }
        catch (ArgumentException exception)
        {
            throw Fail(source, $"{location}.client_cert is invalid.", exception);
        }
    }

    private static CacheMode ParseCacheMode(JsonValue value, string source)
    {
        if (value is not JsonString text)
        {
            throw Fail(source, "cache.mode must be one of off, auto, explicit.");
        }

        return text.Value switch
        {
            "off" => CacheMode.Off,
            "auto" => CacheMode.Auto,
            "explicit" => CacheMode.Explicit,
            _ => throw Fail(source, "cache.mode must be one of off, auto, explicit."),
        };
    }

    private static string CacheModeJson(CacheMode mode) => mode switch
    {
        CacheMode.Off => "off",
        CacheMode.Auto => "auto",
        CacheMode.Explicit => "explicit",
        _ => throw new ArgumentOutOfRangeException(nameof(mode)),
    };

    private static bool RequiredBoolean(JsonValue value, string source, string location)
    {
        if (value is not JsonBoolean boolean)
        {
            throw Fail(source, $"{location} must be a boolean.");
        }

        return boolean.Value;
    }

    private static long RequiredLong(JsonValue value, string source, string location)
    {
        if (value is not JsonInteger integer || integer.Value < long.MinValue || integer.Value > long.MaxValue)
        {
            throw Fail(source, $"{location} must be an integer.");
        }

        return (long)integer.Value;
    }

    private static double RequiredFiniteNumber(JsonValue value, string source, string location)
    {
        var number = value switch
        {
            JsonInteger integer => (double)integer.Value,
            JsonNumber decimalNumber => decimalNumber.Value,
            _ => double.NaN,
        };
        if (!double.IsFinite(number))
        {
            throw Fail(source, $"{location} must be a finite number.");
        }

        return number;
    }

    private static void RejectUnknown(JsonObject raw, IReadOnlySet<string> allowed, string source, string location)
    {
        var unknown = raw.Properties.Select(static property => property.Name).Where(name => !allowed.Contains(name)).ToArray();
        if (unknown.Length != 0)
        {
            throw Fail(source, $"{location} has unknown key(s): {string.Join(", ", unknown.OrderBy(static name => name, StringComparer.Ordinal))}.");
        }
    }

    private static int RequiredInteger(JsonValue value, string source, string location)
    {
        if (value is not JsonInteger integer || integer.Value < int.MinValue || integer.Value > int.MaxValue)
        {
            throw Fail(source, $"{location} must be an integer.");
        }

        return (int)integer.Value;
    }

    private static string RequiredNonBlankString(JsonValue value, string source, string location)
    {
        if (value is not JsonString text || string.IsNullOrWhiteSpace(text.Value))
        {
            throw Fail(source, $"{location} must be a nonblank string.");
        }

        return text.Value;
    }

    private static string? OptionalTruthyString(JsonObject raw, string name, string source, string location)
    {
        if (!raw.TryGetValue(name, out var value) || value is JsonNull)
        {
            return null;
        }

        if (value is not JsonString text)
        {
            throw Fail(source, $"{location}.{name} must be a string.");
        }

        return text.Value.Length == 0 ? null : text.Value;
    }

    private static JsonValue GetOrDefault(JsonObject value, string name, JsonValue fallback) => value.TryGetValue(name, out var found) ? found : fallback;

    private static void EnsureDefaultRouteCanSerialize(Route route)
    {
        if (route.Retry.MaxAttempts != 2 || route.Retry.BackoffBaseS != 0.5 || route.Retry.BackoffMaxS != 30 || !route.HealthGate || route.HealthTtlS != 30)
        {
            throw new ConfigException("A route with custom retry or health policy cannot be serialized by configuration format version 1.");
        }

        if (route.ContextWindowTargets.Count != 0)
        {
            throw new ConfigException("A route with context-window targets cannot be serialized by configuration format version 1.");
        }
    }

    private static IReadOnlyDictionary<InferenceOperation, Route> CopyOperationRoutes(
        IReadOnlyDictionary<InferenceOperation, Route>? operationRoutes)
    {
        var copied = new Dictionary<InferenceOperation, Route>();
        if (operationRoutes is not null)
        {
            foreach (var pair in operationRoutes)
            {
                if (pair.Key is not InferenceOperation.Embedding and not InferenceOperation.Rerank)
                {
                    throw new ConfigException("Operation routes support only embedding and rerank.");
                }

                copied.Add(pair.Key, pair.Value ?? throw new ConfigException("Operation routes cannot contain null routes."));
            }
        }

        return new ReadOnlyDictionary<InferenceOperation, Route>(copied);
    }

    private static string OperationRouteName(InferenceOperation operation) => operation switch
    {
        InferenceOperation.Embedding => "embedding",
        InferenceOperation.Rerank => "rerank",
        _ => throw new ArgumentOutOfRangeException(nameof(operation)),
    };

    private static ConfigException Fail(string source, string detail, Exception? nativeInner = null)
        => new($"Configuration {source}: {detail}", detail: detail, hint: "See the shared configuration guide for supported format version 1.", nativeInner: nativeInner);
}
