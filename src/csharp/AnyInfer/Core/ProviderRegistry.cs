using AnyInfer.Providers;
using AnyInfer.Credentials;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Routing;
using System.Collections.ObjectModel;
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
    int? MaxRepairAttempts,
    ModelCapabilities? ResolvedCapabilities = null);

/// <summary>Identifies the selected per-instance limiter and where its slot is acquired.</summary>
internal readonly record struct PacingSelection(RateLimiter? Limiter, bool UsesOuterSlot);

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
    private readonly HashSet<IAsyncDisposable> _adopted = new(ReferenceEqualityComparer.Instance);
    private readonly HashSet<HttpMessageHandler> _poolOwnedConfiguredHandlers = new(ReferenceEqualityComparer.Instance);
    private readonly IReadOnlyDictionary<string, RateLimiter> _injectedLimiters;
    private readonly Action<TelemetryEvent>? _events;
    private readonly TimeProvider _pacingTimeProvider;
    private static readonly AsyncLocal<FactoryScope?> ActiveFactories = new();
    private bool _closing;

    internal ProviderPool(
        IEnumerable<ProviderRegistration> registrations,
        IReadOnlyDictionary<string, RateLimiter>? injectedLimiters = null,
        Action<TelemetryEvent>? events = null,
        TimeProvider? pacingTimeProvider = null)
    {
        ArgumentNullException.ThrowIfNull(registrations);
        _injectedLimiters = CopyLimiters(injectedLimiters);
        _events = events;
        _pacingTimeProvider = pacingTimeProvider ?? TimeProvider.System;
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

    internal ProviderPool(
        IEnumerable<ProviderSettings>? settings,
        ProviderRegistry descriptors,
        ResolverChain resolver,
        IReadOnlyDictionary<string, RateLimiter>? injectedLimiters = null,
        Action<TelemetryEvent>? events = null,
        TimeProvider? pacingTimeProvider = null)
    {
        ArgumentNullException.ThrowIfNull(descriptors);
        _injectedLimiters = CopyLimiters(injectedLimiters);
        _events = events;
        _pacingTimeProvider = pacingTimeProvider ?? TimeProvider.System;
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
                    providerId: descriptor.Id,
                    baseUrl: supplied.BaseUrl,
                    apiKey: supplied.ApiKey,
                    apiVersion: supplied.ApiVersion,
                    headers: supplied.Headers,
                    options: supplied.Options,
                    timeoutS: supplied.TimeoutS,
                    transport: supplied.Transport,
                    alias: supplied.Alias,
                    limits: supplied.Limits,
                    proxy: supplied.Proxy,
                    verify: supplied.Verify,
                    clientCertificate: supplied.ClientCertificate);
            if (!_instances.TryAdd(executionId, InstanceState.FromSettings(executionId, descriptor, boundSettings)))
            {
                throw ConfigurationError(executionId, "Provider instances must have unique canonical identities.");
            }

            if (supplied.Transport is not null && !handlers.Add(supplied.Transport))
            {
                throw ConfigurationError(supplied.InstanceId, "A transport handler may belong to only one configured provider instance.");
            }

            if (supplied.Transport is not null && descriptor.PoolOwnsConfiguredTransport)
            {
                _poolOwnedConfiguredHandlers.Add(supplied.Transport);
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

    internal async ValueTask<IAsyncDisposable> GetAdapterAsync(
        ResolvedProvider resolved,
        CancellationToken callerToken,
        Func<CancellationToken?>? cancelledParentToken = null,
        CancellationToken callerIdentity = default)
    {
        ArgumentNullException.ThrowIfNull(resolved);
        return await GetAdapterAsync(
            resolved.State,
            callerToken,
            callerIdentity,
            cancelledParentToken).ConfigureAwait(false);
    }

    internal async ValueTask<IAsyncDisposable> GetAdapterAsync(
        InstanceState state,
        CancellationToken callerToken,
        CancellationToken callerIdentity = default,
        Func<CancellationToken?>? cancelledParentToken = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ThrowIfClosing();
        if (state.Registration is { } registration)
        {
            return registration.Adapter;
        }

        ThrowIfFactoryReentry(state);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(callerToken, _lifetime.Token);
        try
        {
            await state.Gate.WaitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (HasOwnedCancellation(callerIdentity, cancelledParentToken))
        {
            ThrowPoolOwnedCancellation(callerIdentity, linked.Token, cancelledParentToken);
            throw;
        }
        try
        {
            ThrowIfClosing();
            ThrowPoolOwnedCancellation(callerIdentity, linked.Token, cancelledParentToken);
            if (state.Adapter is not null)
            {
                return state.Adapter;
            }

            var build = BuildAsync(state, _resolver!, linked.Token, callerIdentity, cancelledParentToken);
            TrackBuild(build);
            IAsyncDisposable adapter;
            try
            {
                adapter = await build.ConfigureAwait(false);
            }
            finally
            {
                UntrackBuild(build);
            }

            if (HasOwnedCancellation(callerIdentity, cancelledParentToken) || linked.IsCancellationRequested)
            {
                MarkTransferredTransportConsumed(state);
                await DisposeUnadoptedAdapterAsync(state, adapter).ConfigureAwait(false);
                ThrowPoolOwnedCancellation(callerIdentity, linked.Token, cancelledParentToken);
            }

            var closing = false;
            var alreadyAdopted = false;
            lock (_gate)
            {
                closing = _closing;
                alreadyAdopted = !closing && _adopted.Contains(adapter);
                if (!closing && !alreadyAdopted)
                {
                    state.Adapter = adapter;
                    _adopted.Add(adapter);
                    state.PendingGovernedHandler = null;
                }
            }

            if (closing)
            {
                MarkTransferredTransportConsumed(state);
                await DisposeUnadoptedAdapterAsync(state, adapter).ConfigureAwait(false);
                throw new ObjectDisposedException(nameof(AsyncClient));
            }

            if (alreadyAdopted)
            {
                MarkTransferredTransportConsumed(state);
                DisposePendingGovernedHandler(state);
                if (HasOwnedCancellation(callerIdentity, cancelledParentToken) || linked.IsCancellationRequested)
                {
                    ThrowPoolOwnedCancellation(callerIdentity, linked.Token, cancelledParentToken);
                }

                lock (_gate)
                {
                    closing = _closing;
                    if (!closing)
                    {
                        state.Adapter = adapter;
                    }
                }

                if (closing)
                {
                    await DisposeUnadoptedAdapterAsync(state, adapter).ConfigureAwait(false);
                    throw new ObjectDisposedException(nameof(AsyncClient));
                }
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

    internal PacingSelection GetPacing(ResolvedProvider resolved)
    {
        ArgumentNullException.ThrowIfNull(resolved);
        return GetPacing(resolved.State);
    }

    private PacingSelection GetPacing(InstanceState state)
    {
        lock (_gate)
        {
            if (state.PacingInitialized)
            {
                return state.Pacing;
            }

            state.PacingInitialized = true;
            if (_injectedLimiters.TryGetValue(state.InstanceId, out var injected))
            {
                state.Pacing = injected.Limits.Active
                    ? new PacingSelection(injected, state.Descriptor?.GovernsOwnTransport ?? true)
                    : default;
                return state.Pacing;
            }

            if (state.Descriptor is not { } descriptor || state.Settings.Limits is not { Active: true } limits)
            {
                return state.Pacing;
            }

            state.Pacing = new PacingSelection(
                new RateLimiter(
                    limits,
                    descriptor.RateLimitHeaders,
                    state.InstanceId,
                    _events,
                    seesResponses: !descriptor.GovernsOwnTransport,
                    _pacingTimeProvider),
                descriptor.GovernsOwnTransport);
            return state.Pacing;
        }
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

        IAsyncDisposable[] adapters;
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

        foreach (var handler in _poolOwnedConfiguredHandlers)
        {
            try
            {
                handler.Dispose();
            }
            catch (Exception exception)
            {
                failure ??= exception;
            }
        }

        try
        {
            _lifetime.Dispose();
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }
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

    private async Task<IAsyncDisposable> BuildAsync(
        InstanceState state,
        ResolverChain resolver,
        CancellationToken cancellationToken,
        CancellationToken callerIdentity = default,
        Func<CancellationToken?>? cancelledParentToken = null)
    {
        var descriptor = state.Descriptor ?? throw new InvalidOperationException("Prebuilt registrations do not require a factory.");
        if (state.TransportConsumed)
        {
            throw ConfigurationError(state.InstanceId, "The configured transport was transferred to a discarded adapter and cannot be rebuilt.");
        }

        var settings = state.Settings;
        if (descriptor.RequiresBaseUrl && string.IsNullOrWhiteSpace(settings.BaseUrl) && string.IsNullOrWhiteSpace(descriptor.DefaultBaseUrl))
        {
            throw ConfigurationError(settings.InstanceId, "The provider requires a base URL.");
        }

        var boundSettings = settings.BaseUrl is null && descriptor.DefaultBaseUrl is not null
            ? ProviderSettings.Of(
                providerId: settings.ProviderId,
                baseUrl: descriptor.DefaultBaseUrl,
                apiKey: settings.ApiKey,
                apiVersion: settings.ApiVersion,
                headers: settings.Headers,
                options: settings.Options,
                timeoutS: settings.TimeoutS,
                transport: settings.Transport,
                alias: settings.Alias,
                limits: settings.Limits,
                proxy: settings.Proxy,
                verify: settings.Verify,
                clientCertificate: settings.ClientCertificate)
            : settings;
        if (settings.Transport is null && boundSettings.HasActiveConnectionSettings && !descriptor.HonorsConnectionSettings)
        {
            throw ConfigurationError(settings.InstanceId, "This provider does not support SDK-owned connection settings.");
        }
        var resolvedKey = await resolver.ResolveAsync(boundSettings.ApiKey, cancellationToken).ConfigureAwait(false);
        ThrowPoolOwnedCancellation(callerIdentity, cancellationToken, cancelledParentToken);
        var apiKeyField = descriptor.Setup.Fields.SingleOrDefault(static field => field.Key == "api_key");
        if (apiKeyField is { Required: true } && string.IsNullOrWhiteSpace(resolvedKey))
        {
            throw ConfigurationError(settings.InstanceId, "The required setup field 'api_key' is missing.");
        }

        var resolvedOptions = await ResolveOptionsAsync(
            descriptor,
            boundSettings,
            resolver,
            cancellationToken,
            callerIdentity,
            cancelledParentToken).ConfigureAwait(false);
        ThrowPoolOwnedCancellation(callerIdentity, cancellationToken, cancelledParentToken);
        var config = new ProviderConfig(boundSettings, descriptor.Id, resolvedKey, resolvedOptions)
        {
            TransportOwnedByPool = descriptor.PoolOwnsConfiguredTransport && boundSettings.Transport is not null,
        };
        ThrowPoolOwnedCancellation(callerIdentity, cancellationToken, cancelledParentToken);
        GovernedHttpMessageHandler? governedHandler = null;
        var transfersRawTransport = false;
        var factoryReturned = false;
        var pacing = GetPacing(state);
        if (pacing.Limiter is not null && !pacing.UsesOuterSlot)
        {
            var (rawTransport, ownsRawTransport, transfersRaw) = CreateRawTransport(config, descriptor, cancellationToken);
            governedHandler = new GovernedHttpMessageHandler(rawTransport, pacing.Limiter, ownsRawTransport);
            config = config.WithTransport(governedHandler, transportOwnedByPool: false);
            transfersRawTransport = transfersRaw;
        }

        try
        {
            using var scope = PushFactoryScope(state);
            var adapter = await descriptor.Factory(config, cancellationToken).ConfigureAwait(false);
            factoryReturned = true;
            state.PendingTransferredTransport = transfersRawTransport;
            state.PendingGovernedHandler = governedHandler;
            if (adapter is null)
            {
                MarkTransferredTransportConsumed(state);
                DisposePendingGovernedHandler(state);

                throw ConfigurationError(state.InstanceId, "The provider factory returned no adapter.");
            }

            await ValidateDeclaredProtocolsAsync(state, descriptor, adapter).ConfigureAwait(false);
            return adapter;
        }
        catch
        {
            if (!factoryReturned && governedHandler is not null)
            {
                try
                {
                    governedHandler.Dispose();
                }
                catch
                {
                }

                if (transfersRawTransport)
                {
                    state.TransportConsumed = true;
                }
            }

            throw;
        }
    }

    private async ValueTask ValidateDeclaredProtocolsAsync(
        InstanceState state,
        ProviderDescriptor descriptor,
        IAsyncDisposable adapter)
    {
        var invalid = descriptor.Operations.Any(operation => operation switch
        {
            InferenceOperation.Generation => adapter is not IGeneratesText,
            InferenceOperation.Embedding => adapter is not IEmbedsText,
            InferenceOperation.Rerank => adapter is not IReranksText,
            _ => true,
        });
        if (!invalid)
        {
            return;
        }

        MarkTransferredTransportConsumed(state);
        await DisposeUnadoptedAdapterAsync(state, adapter).ConfigureAwait(false);
        throw ConfigurationError(
            state.InstanceId,
            "The provider factory returned an adapter that does not implement every declared operation.");
    }

    private async ValueTask DisposeUnadoptedAdapterAsync(InstanceState state, IAsyncDisposable adapter)
    {
        Exception? failure = null;
        if (!IsAdopted(adapter))
        {
            try
            {
                await adapter.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        }

        try
        {
            DisposePendingGovernedHandler(state);
        }
        catch (Exception exception)
        {
            failure ??= exception;
        }

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private bool IsAdopted(IAsyncDisposable adapter)
    {
        lock (_gate)
        {
            return _adopted.Contains(adapter);
        }
    }

    private static void DisposePendingGovernedHandler(InstanceState state)
    {
        var handler = state.PendingGovernedHandler;
        state.PendingGovernedHandler = null;
        handler?.Dispose();
    }

    private static bool HasOwnedCancellation(
        CancellationToken callerIdentity,
        Func<CancellationToken?>? cancelledParentToken) =>
        cancelledParentToken?.Invoke() is not null || callerIdentity.IsCancellationRequested;

    private static void ThrowPoolOwnedCancellation(
        CancellationToken callerIdentity,
        CancellationToken linkedToken,
        Func<CancellationToken?>? cancelledParentToken = null)
    {
        if (cancelledParentToken?.Invoke() is { } parent)
        {
            throw new OperationCanceledException(parent);
        }

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
        CancellationToken callerIdentity = default,
        Func<CancellationToken?>? cancelledParentToken = null)
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
            if (value is null && field.DefaultValue.Length != 0)
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
                ThrowPoolOwnedCancellation(callerIdentity, cancellationToken, cancelledParentToken);
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

    private static (HttpMessageHandler Transport, bool OwnsTransport, bool TransfersTransport) CreateRawTransport(
        ProviderConfig config,
        ProviderDescriptor descriptor,
        CancellationToken cancellationToken)
    {
        if (config.Transport is null)
        {
            return (ConnectionHandlerFactory.CreateOwned(config, cancellationToken), true, false);
        }

        if (descriptor.PoolOwnsConfiguredTransport)
        {
            return (config.Transport, false, false);
        }

        return (config.Transport, true, true);
    }

    private static IReadOnlyDictionary<string, RateLimiter> CopyLimiters(
        IReadOnlyDictionary<string, RateLimiter>? limiters)
    {
        var copied = new Dictionary<string, RateLimiter>(StringComparer.Ordinal);
        if (limiters is null)
        {
            return new ReadOnlyDictionary<string, RateLimiter>(copied);
        }

        foreach (var (identifier, limiter) in limiters)
        {
            ArgumentNullException.ThrowIfNull(limiter);
            var normalized = ProviderSettings.NormalizeId(identifier, nameof(limiters));
            if (!copied.TryAdd(normalized, limiter))
            {
                throw new ArgumentException("Injected rate limiters must have unique canonical instance IDs.", nameof(limiters));
            }
        }

        return new ReadOnlyDictionary<string, RateLimiter>(copied);
    }

    private static void MarkTransferredTransportConsumed(InstanceState state)
    {
        if (state.PendingTransferredTransport)
        {
            state.TransportConsumed = true;
        }
    }

    private static void ThrowIfFactoryReentry(InstanceState state)
    {
        for (var scope = ActiveFactories.Value; scope is not null; scope = scope.Parent)
        {
            if (scope.Active && ReferenceEquals(scope.State, state))
            {
                throw new InvalidOperationException("A provider factory cannot re-enter construction for the same configured instance.");
            }
        }
    }

    private static FactoryScope PushFactoryScope(InstanceState state)
    {
        var scope = new FactoryScope(state, ActiveFactories.Value);
        ActiveFactories.Value = scope;
        return scope;
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

    private sealed class FactoryScope(InstanceState state, FactoryScope? parent) : IDisposable
    {
        private int _active = 1;

        internal InstanceState State { get; } = state;
        internal FactoryScope? Parent { get; } = parent;
        internal bool Active => Volatile.Read(ref _active) != 0;

        public void Dispose()
        {
            Interlocked.Exchange(ref _active, 0);
            if (ReferenceEquals(ActiveFactories.Value, this))
            {
                ActiveFactories.Value = Parent;
            }
        }
    }

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
        internal IAsyncDisposable? Adapter { get; set; }
        internal bool PacingInitialized { get; set; }
        internal PacingSelection Pacing { get; set; }
        internal GovernedHttpMessageHandler? PendingGovernedHandler { get; set; }
        internal bool PendingTransferredTransport { get; set; }
        internal bool TransportConsumed { get; set; }

        internal static InstanceState FromSettings(string instanceId, ProviderDescriptor descriptor, ProviderSettings settings) =>
            new(instanceId, settings, descriptor, null);

        internal static InstanceState FromRegistration(string instanceId, ProviderRegistration registration) =>
            new(instanceId, ProviderSettings.Of(instanceId), null, registration)
            {
                Adapter = registration.Adapter,
            };
    }
}
