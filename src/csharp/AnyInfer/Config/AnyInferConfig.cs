using AnyInfer.Credentials;
using AnyInfer.Json;
using AnyInfer.Providers;
using System.Numerics;
using System.Text;

namespace AnyInfer.Config;

/// <summary>Inert, validated version 1 configuration shared by C# AnyInfer integrations.</summary>
public sealed class AnyInferConfig
{
    /// <summary>The only configuration format version accepted by this SDK phase.</summary>
    public const int FormatVersion1 = 1;

    /// <summary>The largest UTF-8 configuration document accepted by this SDK phase.</summary>
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
        "operation_routes", "context", "history", "cache", "observers", "arena", "arenas", "mcp",
    };
    private static readonly HashSet<string> IdentityKeys = new(StringComparer.Ordinal) { "id", "adapter", "provider_id", "alias", "enabled" };
    private static readonly HashSet<string> SettingKeys = new(StringComparer.Ordinal)
    {
        "base_url", "api_key", "api_version", "headers", "options", "timeout_s", "values", "limits", "proxy", "verify", "client_cert",
    };
    private static readonly HashSet<string> DirectKeys = new(StringComparer.Ordinal) { "base_url", "api_key", "api_version" };

    /// <summary>Creates an immutable configuration without resolving credentials or constructing adapters.</summary>
    public AnyInferConfig(IEnumerable<ProviderSettings>? providers = null, Route? route = null, Repair? repair = null, int formatVersion = FormatVersion1)
    {
        if (formatVersion != FormatVersion1)
        {
            throw new ConfigException("The configuration format version is unsupported.");
        }

        Providers = Array.AsReadOnly((providers ?? []).Select(static provider => provider ?? throw new ArgumentException("Providers cannot contain null references.")).ToArray());
        Route = route;
        Repair = repair;
        FormatVersion = formatVersion;
    }

    /// <summary>Gets provider settings in declaration order.</summary>
    public IReadOnlyList<ProviderSettings> Providers { get; }

    /// <summary>Gets the optional default generation route.</summary>
    public Route? Route { get; }

    /// <summary>Gets the optional schema-repair budget.</summary>
    public Repair? Repair { get; }

    /// <summary>Gets the parsed format version.</summary>
    public int FormatVersion { get; }

    /// <summary>Loads and validates a UTF-8 configuration document from an explicit path.</summary>
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

    /// <summary>Writes this configuration atomically only when the destination is new, unless overwrite is explicit.</summary>
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
        return new AnyInferConfig(providers, route, repair, version);
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
        ValidateInactiveConnectionSettings(raw, source, location);
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

        return new ProviderSettings(ProviderRegistry.NormalizeProviderId(engine), baseUrl ?? descriptor.DefaultBaseUrl, apiKey, apiVersion, headers, mergedOptions.Properties.Count == 0 ? null : mergedOptions, timeout, alias: instanceId == ProviderRegistry.NormalizeProviderId(engine) ? null : instanceId);
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

    private static void ValidateInactiveConnectionSettings(JsonObject raw, string source, string location)
    {
        foreach (var name in new[] { "limits", "proxy", "client_cert" })
        {
            if (raw.TryGetValue(name, out var value) && value is not JsonNull)
            {
                throw Fail(source, $"{location}.{name} is not implemented in this SDK phase.");
            }
        }

        if (raw.TryGetValue("verify", out var verify) && verify is not JsonNull && (verify is not JsonBoolean boolean || !boolean.Value))
        {
            throw Fail(source, $"{location}.verify is not implemented in this SDK phase.");
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
    }

    private static ConfigException Fail(string source, string detail, Exception? nativeInner = null)
        => new($"Configuration {source}: {detail}", detail: detail, hint: "See the shared configuration guide for supported format version 1.", nativeInner: nativeInner);
}
