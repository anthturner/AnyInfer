using AnyInfer.Capabilities;

namespace AnyInfer.Core;

/// <summary>Immutable client services shared by PublicSdk generation policy phases.</summary>
internal sealed class GenerationPolicyContext
{
    private readonly CachePrefixState _prefixes;

    internal GenerationPolicyContext(
        GenerationRequest request,
        CachePolicy? cachePolicy,
        ITokenEstimator? estimator,
        CachePrefixState prefixes,
        TimeProvider? entryTimeProvider)
        : this(request, cachePolicy, estimator, prefixes, null, null, false, entryTimeProvider)
    {
    }

    internal GenerationPolicyContext(
        GenerationRequest request,
        CachePolicy? cachePolicy,
        ITokenEstimator? estimator,
        CachePrefixState prefixes,
        SpendPolicy? spendPolicy = null,
        SpendLedger? ledger = null,
        bool contextGate = false,
        TimeProvider? entryTimeProvider = null)
    {
        Request = request ?? throw new ArgumentNullException(nameof(request));
        CachePolicy = cachePolicy;
        Estimator = estimator;
        _prefixes = prefixes ?? throw new ArgumentNullException(nameof(prefixes));
        SpendPolicy = spendPolicy;
        Ledger = ledger;
        ContextGate = contextGate;
        EntryTimeProvider = entryTimeProvider ?? TimeProvider.System;
    }

    internal GenerationRequest Request { get; }
    internal CachePolicy? CachePolicy { get; }
    internal ITokenEstimator? Estimator { get; }
    internal SpendPolicy? SpendPolicy { get; }
    internal SpendLedger? Ledger { get; }
    internal bool ContextGate { get; }
    internal TimeProvider EntryTimeProvider { get; }

    /// <summary>Records one target's latest cache-prefix signature for this client lifetime.</summary>
    internal bool PrefixChanged(ResolvedTarget target, string signature)
        => _prefixes.Update(target, signature);
}

/// <summary>Stores client-local cache-prefix facts without invoking application callbacks.</summary>
internal sealed class CachePrefixState
{
    private readonly object _gate = new();
    private readonly Dictionary<string, string> _prefixes = new(StringComparer.Ordinal);

    internal bool Update(ResolvedTarget target, string signature)
    {
        ArgumentNullException.ThrowIfNull(signature);
        var key = target.ToString();
        lock (_gate)
        {
            if (!_prefixes.TryGetValue(key, out var previous))
            {
                _prefixes[key] = signature;
                return false;
            }

            if (string.Equals(previous, signature, StringComparison.Ordinal))
            {
                return false;
            }

            _prefixes[key] = signature;
            return true;
        }
    }
}
