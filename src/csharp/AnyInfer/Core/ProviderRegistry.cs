using AnyInfer.Providers;
using AnyInfer.Credentials;
using System.Runtime.ExceptionServices;

namespace AnyInfer.Core;

internal sealed record ResolvedProvider(
    ResolvedTarget Target,
    ProviderDescriptor? Descriptor,
    ProviderRegistration? Registration,
    ProviderSettings Settings,
    StructuredOutputProfile Capabilities,
    int? MaxRepairAttempts,
    ProviderPool.InstanceState State);

internal sealed record TargetMetadata(
    ResolvedTarget Target,
    ProviderDescriptor? Descriptor,
    ProviderRegistration? Registration,
    ProviderSettings Settings,
    StructuredOutputProfile Capabilities,
    int? MaxRepairAttempts);

/// <summary>Client-owned lazy adapter pool. Descriptor lookup remains public registry work.</summary>
internal sealed class ProviderPool : IAsyncDisposable
{
    private readonly ProviderRegistry? _descriptors;
    private readonly ResolverChain? _resolver;
    private readonly Dictionary<string, InstanceState> _instances;
    private readonly IReadOnlyList<AnyInfer.Catalog.CatalogProviderBinding> _bindings;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly object _gate = new();
    private readonly HashSet<Task> _builds = [];
    private readonly HashSet<IProviderAdapter> _adopted = new(ReferenceEqualityComparer.Instance);
    private bool _closing;

    internal ProviderPool(IEnumerable<ProviderRegistration> registrations)
    {
        ArgumentNullException.ThrowIfNull(registrations);
        _instances = new Dictionary<string, InstanceState>(StringComparer.Ordinal);
        foreach (var registration in registrations)
        {
            ArgumentNullException.ThrowIfNull(registration);
            var identifier = ProviderSettings.NormalizeId(registration.ProviderId, nameof(registrations));
            if (!_instances.TryAdd(identifier, InstanceState.FromRegistration(identifier, registration)))
            {
                throw new ArgumentException("Provider registrations must have unique provider IDs.", nameof(registrations));
            }

            _adopted.Add(registration.Adapter);
        }
        _bindings = Array.AsReadOnly(_instances.Values.Select(state => new AnyInfer.Catalog.CatalogProviderBinding(state.InstanceId, state.InstanceId)).ToArray());
    }

    internal ProviderPool(IEnumerable<ProviderSettings>? settings, ProviderRegistry descriptors, ResolverChain resolver)
    {
        ArgumentNullException.ThrowIfNull(descriptors);
        _descriptors = new ProviderRegistry(descriptors.Descriptors);
        _resolver = resolver ?? throw new ArgumentNullException(nameof(resolver));
        _instances = new Dictionary<string, InstanceState>(StringComparer.Ordinal);
        var handlers = new HashSet<HttpMessageHandler>(ReferenceEqualityComparer.Instance);
        foreach (var supplied in settings ?? [])
        {
            ArgumentNullException.ThrowIfNull(supplied);
            var descriptor = descriptors.Get(supplied.ProviderId);
            var executionId = supplied.Alias is null || supplied.Alias == descriptor.Id
                ? descriptor.Id
                : supplied.Alias;
            if (supplied.Alias is not null && supplied.Alias != descriptor.Id && descriptors.Has(supplied.Alias))
            {
                throw ConfigurationError(supplied.InstanceId, "A configured instance alias cannot shadow a provider ID or descriptor alias.");
            }

            var boundSettings = executionId == supplied.InstanceId
                ? supplied
                : ProviderSettings.Of(
                    descriptor.Id,
                    supplied.BaseUrl,
                    supplied.ApiKey,
                    supplied.ApiVersion,
                    supplied.Headers,
                    supplied.Options,
                    supplied.TimeoutS,
                    supplied.Transport,
                    supplied.Alias);
            if (!_instances.TryAdd(executionId, InstanceState.FromSettings(executionId, descriptor, boundSettings)))
            {
                throw ConfigurationError(executionId, "Provider instances must have unique canonical identities.");
            }

            if (supplied.Transport is not null && !handlers.Add(supplied.Transport))
            {
                throw ConfigurationError(supplied.InstanceId, "A transport handler may belong to only one configured provider instance.");
            }
        }
        _bindings = Array.AsReadOnly(_instances.Values.Select(state => new AnyInfer.Catalog.CatalogProviderBinding(state.InstanceId, state.Descriptor!.Id)).ToArray());
    }

    internal TargetMetadata ResolveMetadata(string rawTarget)
    {
        ArgumentNullException.ThrowIfNull(rawTarget);
        if (string.IsNullOrWhiteSpace(rawTarget))
        {
            throw ConfigureError("Target is empty.");
        }

        var separator = rawTarget.IndexOf(':');
        if (separator < 0)
        {
            throw ConfigureError("The target does not include a provider and model.");
        }

        var rawProvider = rawTarget[..separator];
        var model = rawTarget[(separator + 1)..].Trim();
        if (rawProvider.Length == 0 || model.Length == 0)
        {
            throw ConfigureError("Target provider or model is empty.");
        }

        var normalized = ProviderSettings.NormalizeId(rawProvider, nameof(rawTarget));
        InstanceState? state;
        lock (_gate)
        {
            _instances.TryGetValue(normalized, out state);
        }

        if (state is null)
        {
            if (_descriptors is null)
            {
                throw ConfigureError("Target provider is not registered.");
            }

            var descriptor = _descriptors.Get(normalized);
            state = InstanceState.FromSettings(descriptor.Id, descriptor, ProviderSettings.Of(descriptor.Id));
        }

        var capabilities = state.Registration is { } registration
            ? registration.StructuredOutputProfiles.TryGetValue(model, out var profile) ? profile : new StructuredOutputProfile()
            : state.Descriptor!.StructuredOutputProfiles.TryGetValue(model, out var descriptorProfile) ? descriptorProfile : new StructuredOutputProfile();
        var maximumRepairs = state.Registration?.MaxRepairAttempts ?? state.Descriptor?.MaxRepairAttempts;
        return new TargetMetadata(
            new ResolvedTarget(state.InstanceId, model),
            state.Descriptor,
            state.Registration,
            state.Settings,
            capabilities,
            maximumRepairs);
    }

    internal IReadOnlyList<AnyInfer.Catalog.CatalogProviderBinding> Bindings
    {
        get { return _bindings; }
    }

    internal ProviderRegistry? DescriptorSnapshot => _descriptors;

    internal TargetMetadata ResolveMetadata(ResolvedTarget target)
    {
        var resolved = ResolveMetadata($"{target.ProviderId}:{target.Model}");
        return resolved with { Target = target };
    }

    internal ProviderLocality EffectiveLocality(TargetMetadata provider)
    {
        var descriptor = provider.Descriptor;
        if (descriptor is null || descriptor.Locality != ProviderLocality.Local) return descriptor?.Locality ?? ProviderLocality.Hosted;
        var baseUrl = provider.Settings.BaseUrl ?? descriptor.DefaultBaseUrl;
        return baseUrl is null || (Uri.TryCreate(baseUrl, UriKind.Absolute, out var uri) && uri.IsLoopback) ? ProviderLocality.Local : ProviderLocality.Remote;
    }

    internal async ValueTask<IProviderAdapter> GetAdapterAsync(ResolvedProvider resolved, CancellationToken callerToken)
    {
        ArgumentNullException.ThrowIfNull(resolved);
        return await GetAdapterAsync(resolved.State, callerToken).ConfigureAwait(false);
    }

    internal async ValueTask<IProviderAdapter> GetAdapterAsync(
        InstanceState state,
        CancellationToken callerToken,
        CancellationToken callerIdentity = default)
    {
        ArgumentNullException.ThrowIfNull(state);
        ThrowIfClosing();
        if (state.Registration is { } registration)
        {
            return registration.Adapter;
        }

        using var linked = CancellationTokenSource.CreateLinkedTokenSource(callerToken, _lifetime.Token);
        try
        {
            await state.Gate.WaitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (callerIdentity.IsCancellationRequested)
        {
            throw new OperationCanceledException(callerIdentity);
        }
        try
        {
            ThrowIfClosing();
            if (state.Adapter is not null)
            {
                return state.Adapter;
            }

            var build = BuildAsync(state, _resolver!, linked.Token, callerIdentity);
            TrackBuild(build);
            IProviderAdapter adapter;
            try
            {
                adapter = await build.ConfigureAwait(false);
            }
            finally
            {
                UntrackBuild(build);
            }

            if (linked.IsCancellationRequested)
            {
                await adapter.DisposeAsync().ConfigureAwait(false);
                ThrowPoolOwnedCancellation(callerIdentity, linked.Token);
            }

            var closing = false;
            lock (_gate)
            {
                closing = _closing;
                if (!closing)
                {
                    state.Adapter = adapter;
                    _adopted.Add(adapter);
                }
            }

            if (closing)
            {
                await adapter.DisposeAsync().ConfigureAwait(false);
                throw new ObjectDisposedException(nameof(AsyncClient));
            }

            return adapter;
        }
        finally
        {
            state.Gate.Release();
        }
    }

    internal InstanceState ResolveLifecycleInstance(string providerId)
    {
        ArgumentNullException.ThrowIfNull(providerId);
        var normalized = ProviderSettings.NormalizeId(providerId, nameof(providerId));
        lock (_gate)
        {
            if (_instances.TryGetValue(normalized, out var configured))
            {
                return configured;
            }
        }

        if (_descriptors is null)
        {
            throw ConfigureError("Provider is not registered.");
        }

        return GetOrCreateDefaultState(_descriptors.Get(normalized));
    }

    internal ResolvedProvider Materialize(TargetMetadata metadata)
    {
        InstanceState state;
        lock (_gate)
        {
            if (!_instances.TryGetValue(metadata.Target.ProviderId, out var existing))
            {
                if (metadata.Descriptor is null)
                {
                    throw ConfigureError("Target provider is not registered.");
                }
                state = GetOrCreateDefaultState(metadata.Descriptor);
            }
            else
            {
                state = existing;
            }
        }
        return new ResolvedProvider(metadata.Target, state.Descriptor, state.Registration, state.Settings,
            metadata.Capabilities, metadata.MaxRepairAttempts, state);
    }

    public async ValueTask DisposeAsync()
    {
        Task[] builds;
        InstanceState[] states;
        lock (_gate)
        {
            if (_closing)
            {
                return;
            }

            _closing = true;
            builds = _builds.ToArray();
            states = _instances.Values.ToArray();
        }

        Exception? failure = null;
        try
        {
            _lifetime.Cancel();
        }
        catch (Exception exception)
        {
            failure = exception;
        }

        foreach (var build in builds)
        {
            try
            {
                await build.ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        // A factory can begin between its task creation and build tracking. Joining every
        // per-instance gate after lifetime cancellation closes that narrow race as well.
        foreach (var state in states)
        {
            await state.Gate.WaitAsync().ConfigureAwait(false);
            state.Gate.Release();
        }

        IProviderAdapter[] adapters;
        lock (_gate)
        {
            adapters = _adopted.ToArray();
            _adopted.Clear();
        }

        foreach (var adapter in adapters)
        {
            try
            {
                await adapter.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        _lifetime.Dispose();
        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private InstanceState GetOrCreateDefaultState(ProviderDescriptor descriptor)
    {
        lock (_gate)
        {
            if (_closing)
            {
                throw new ObjectDisposedException(nameof(AsyncClient));
            }

            if (_instances.TryGetValue(descriptor.Id, out var existing))
            {
                return existing;
            }

            var state = InstanceState.FromSettings(descriptor.Id, descriptor, ProviderSettings.Of(descriptor.Id));
            _instances.Add(descriptor.Id, state);
            return state;
        }
    }

    private static async Task<IProviderAdapter> BuildAsync(
        InstanceState state,
        ResolverChain resolver,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity = default)
    {
        var descriptor = state.Descriptor ?? throw new InvalidOperationException("Prebuilt registrations do not require a factory.");
        var settings = state.Settings;
        if (descriptor.RequiresBaseUrl && string.IsNullOrWhiteSpace(settings.BaseUrl) && string.IsNullOrWhiteSpace(descriptor.DefaultBaseUrl))
        {
            throw ConfigurationError(settings.InstanceId, "The provider requires a base URL.");
        }

        var boundSettings = settings.BaseUrl is null && descriptor.DefaultBaseUrl is not null
            ? ProviderSettings.Of(settings.ProviderId, descriptor.DefaultBaseUrl, settings.ApiKey, settings.ApiVersion, settings.Headers, settings.Options, settings.TimeoutS, settings.Transport, settings.Alias)
            : settings;
        var resolvedKey = await resolver.ResolveAsync(boundSettings.ApiKey, cancellationToken).ConfigureAwait(false);
        ThrowPoolOwnedCancellation(callerIdentity, cancellationToken);
        var apiKeyField = descriptor.Setup.Fields.SingleOrDefault(static field => field.Key == "api_key");
        if (apiKeyField is { Required: true } && string.IsNullOrWhiteSpace(resolvedKey))
        {
            throw ConfigurationError(settings.InstanceId, "The required setup field 'api_key' is missing.");
        }

        var resolvedOptions = await ResolveOptionsAsync(descriptor, boundSettings, resolver, cancellationToken, callerIdentity).ConfigureAwait(false);
        ThrowPoolOwnedCancellation(callerIdentity, cancellationToken);
        var config = new ProviderConfig(boundSettings, descriptor.Id, resolvedKey, resolvedOptions);
        ThrowPoolOwnedCancellation(callerIdentity, cancellationToken);
        return await descriptor.Factory(config, cancellationToken).ConfigureAwait(false);
    }

    private static void ThrowPoolOwnedCancellation(CancellationToken callerIdentity, CancellationToken linkedToken)
    {
        if (callerIdentity.IsCancellationRequested)
        {
            throw new OperationCanceledException(callerIdentity);
        }

        linkedToken.ThrowIfCancellationRequested();
    }

    private static async ValueTask<AnyInfer.Json.JsonObject?> ResolveOptionsAsync(
        ProviderDescriptor descriptor,
        ProviderSettings settings,
        ResolverChain resolver,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity = default)
    {
        var options = settings.Options?.Properties.ToDictionary(
            static property => property.Name,
            static property => property.Value,
            StringComparer.Ordinal) ?? new Dictionary<string, AnyInfer.Json.JsonValue>(StringComparer.Ordinal);

        foreach (var field in descriptor.Setup.Fields)
        {
            if (field.Key is "base_url" or "api_key" or "api_version")
            {
                ValidateBuiltInSetting(field, settings, settings.InstanceId);
                continue;
            }

            options.TryGetValue(field.Key, out var value);
            if (value is null && field.DefaultValue is not null)
            {
                value = new AnyInfer.Json.JsonString(field.DefaultValue);
                options.Add(field.Key, value);
            }

            if (field.Required && value is null)
            {
                throw ConfigurationError(settings.InstanceId, $"The required setup field '{field.Key}' is missing.");
            }

            if (value is null)
            {
                continue;
            }

            if (value is not AnyInfer.Json.JsonString text)
            {
                throw ConfigurationError(settings.InstanceId, $"The setup field '{field.Key}' must be text.");
            }

            if (field.Kind == "choice" && !field.Choices.Contains(text.Value, StringComparer.Ordinal))
            {
                throw ConfigurationError(settings.InstanceId, $"The setup field '{field.Key}' has an unsupported value.");
            }

            if (field.Kind == "secret")
            {
                var resolved = await resolver.ResolveAsync(text.Value, cancellationToken).ConfigureAwait(false);
                ThrowPoolOwnedCancellation(callerIdentity, cancellationToken);
                if (resolved is null)
                {
                    if (field.Required)
                    {
                        throw ConfigurationError(settings.InstanceId, $"The required setup field '{field.Key}' is missing.");
                    }

                    options.Remove(field.Key);
                }
                else
                {
                    options[field.Key] = new AnyInfer.Json.JsonString(resolved);
                }
            }
        }

        return options.Count == 0
            ? null
            : new AnyInfer.Json.JsonObject(options.Select(static option => new AnyInfer.Json.JsonProperty(option.Key, option.Value)));
    }

    private static void ValidateBuiltInSetting(SetupField field, ProviderSettings settings, string providerId)
    {
        string? value = field.Key switch
        {
            "base_url" => settings.BaseUrl,
            "api_key" => settings.ApiKey,
            "api_version" => settings.ApiVersion,
            _ => null,
        };
        if (field.Required && string.IsNullOrWhiteSpace(value))
        {
            throw ConfigurationError(providerId, $"The required setup field '{field.Key}' is missing.");
        }
    }

    private void TrackBuild(Task build)
    {
        lock (_gate)
        {
            _builds.Add(build);
        }
    }

    private void UntrackBuild(Task build)
    {
        lock (_gate)
        {
            _builds.Remove(build);
        }
    }

    private void ThrowIfClosing()
    {
        lock (_gate)
        {
            if (_closing)
            {
                throw new ObjectDisposedException(nameof(AsyncClient));
            }
        }
    }

    private AnyInferException ConfigureError(string detail) => _descriptors is null
        ? new ProviderException("The target cannot be configured.", "invalid_request", retryable: false, phase: "configure", detail: detail)
        : ConfigurationError(null, detail);

    private static ConfigException ConfigurationError(string? provider, string detail, Exception? nativeInner = null) =>
        new("The provider configuration is invalid.", provider, detail, nativeInner: nativeInner);

    internal sealed class InstanceState
    {
        private InstanceState(string instanceId, ProviderSettings settings, ProviderDescriptor? descriptor, ProviderRegistration? registration)
        {
            InstanceId = instanceId;
            Settings = settings;
            Descriptor = descriptor;
            Registration = registration;
        }

        internal string InstanceId { get; }
        internal ProviderSettings Settings { get; }
        internal ProviderDescriptor? Descriptor { get; }
        internal ProviderRegistration? Registration { get; }
        internal SemaphoreSlim Gate { get; } = new(1, 1);
        internal IProviderAdapter? Adapter { get; set; }

        internal static InstanceState FromSettings(string instanceId, ProviderDescriptor descriptor, ProviderSettings settings) =>
            new(instanceId, settings, descriptor, null);

        internal static InstanceState FromRegistration(string instanceId, ProviderRegistration registration) =>
            new(instanceId, ProviderSettings.Of(instanceId), null, registration)
            {
                Adapter = registration.Adapter,
            };
    }
}
