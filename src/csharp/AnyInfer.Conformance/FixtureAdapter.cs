using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using AnyInfer.Json;
using AnyInfer.Providers;

namespace AnyInfer.Conformance;

/// <summary>Creates a fresh scripted adapter for one released fixture script.</summary>
internal sealed class FixtureAdapter : IProviderAdapter
{
    private readonly JsonArray _script;
    private readonly FixtureGates? _gates;
    private int _nextEntry;
    private int _disposed;

    private FixtureAdapter(JsonArray script, FixtureGates? gates)
    {
        _script = script ?? throw new ArgumentNullException(nameof(script));
        _gates = gates;
    }

    /// <summary>Creates a fresh adapter which owns only the supplied script.</summary>
    internal static FixtureAdapter Create(JsonArray script, FixtureGates? gates = null)
    {
        FixtureScriptValidation.ValidateScript(script);
        return new FixtureAdapter(script, gates);
    }

    /// <summary>Gets the number of entries claimed when their enumerations first advanced.</summary>
    internal int CallCount => Math.Min(Volatile.Read(ref _nextEntry), _script.Items.Count);

    /// <summary>Gets the number of unclaimed script entries.</summary>
    internal int RemainingEntries => Math.Max(0, _script.Items.Count - Volatile.Read(ref _nextEntry));

    /// <inheritdoc />
    public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ThrowIfDisposed();
        return GenerateCoreAsync(cancellationToken);
    }

    /// <inheritdoc />
    public ValueTask DisposeAsync()
    {
        Interlocked.Exchange(ref _disposed, 1);
        return ValueTask.CompletedTask;
    }

    private async IAsyncEnumerable<AdapterEvent> GenerateCoreAsync(
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ThrowIfDisposed();
        var entryIndex = Interlocked.Increment(ref _nextEntry) - 1;
        if (entryIndex >= _script.Items.Count)
        {
            throw new InvalidOperationException("Fixture adapter script is exhausted.");
        }

        if (_script.Items[entryIndex] is not JsonObject entry)
        {
            throw new InvalidOperationException("Fixture adapter script entry must be an object.");
        }

        var cleanupFailure = ReadFailure(entry, "fail_in_cleanup", FailureLocation.Cleanup);
        var finalYielded = false;
        try
        {
            if (entry.TryGetValue("fail", out var immediateFailure) && !entry.TryGetValue("events", out _))
            {
                throw CreateProviderException(ReadFailureValue(immediateFailure, FailureLocation.Entry));
            }

            if (!entry.TryGetValue("events", out var eventsValue) || eventsValue is not JsonArray events)
            {
                throw new InvalidOperationException("Fixture adapter script entry requires events or fail.");
            }

            foreach (var item in events.Items)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (item is not JsonObject eventObject)
                {
                    throw new InvalidOperationException("Fixture adapter event must be an object.");
                }

                if (eventObject.TryGetValue("await_release", out var releaseValue))
                {
                    if (_gates is null)
                    {
                        throw new InvalidOperationException("Fixture adapter await_release requires FixtureGates.");
                    }

                    await _gates.WaitAsync(ReadString(releaseValue, "await_release"), cancellationToken).ConfigureAwait(false);
                    continue;
                }

                if (eventObject.TryGetValue("text", out var textValue))
                {
                    yield return new AdapterTextDelta(ReadString(textValue, "text"));
                    continue;
                }

                if (eventObject.TryGetValue("usage", out var usageValue))
                {
                    // A script-level null usage is an actual update whose six counters are all null.
                    // Final-event usage remains nullable and therefore uses ReadUsage directly below.
                    yield return new AdapterUsage(ReadUsage(usageValue) ?? new Usage());
                    continue;
                }

                if (eventObject.TryGetValue("final", out var finalValue))
                {
                    if (finalValue is not JsonObject final)
                    {
                        throw new InvalidOperationException("Fixture adapter final event must be an object.");
                    }

                    var finishReason = final.TryGetValue("finish_reason", out var reasonValue)
                        ? ReadString(reasonValue, "finish_reason")
                        : "stop";
                    var usage = final.TryGetValue("usage", out var finalUsageValue)
                        ? ReadUsage(finalUsageValue)
                        : null;
                    finalYielded = true;
                    yield return new AdapterFinal(finishReason, usage);
                    continue;
                }

                throw new InvalidOperationException("Fixture adapter event has no supported member.");
            }

            if (entry.TryGetValue("fail", out var terminalFailure))
            {
                throw CreateProviderException(ReadFailureValue(terminalFailure, FailureLocation.Terminal));
            }
        }
        finally
        {
            if (cleanupFailure is not null && finalYielded)
            {
                throw CreateProviderException(cleanupFailure);
            }
        }
    }

    private static ScriptFailure? ReadFailure(JsonObject entry, string property, FailureLocation location)
    {
        if (!entry.TryGetValue(property, out var value))
        {
            return null;
        }

        return ReadFailureValue(value, location);
    }

    private static ScriptFailure ReadFailureValue(JsonValue value, FailureLocation location)
    {
        if (value is not JsonObject failure ||
            !failure.TryGetValue("category", out var categoryValue))
        {
            throw new InvalidOperationException("Fixture adapter failure requires category.");
        }

        var category = ReadString(categoryValue, "category");
        var retryable = failure.TryGetValue("retryable", out var retryableValue)
            ? ReadBoolean(retryableValue, "retryable")
            : DefaultRetryable(category);
        var retryAfter = failure.TryGetValue("retry_after_s", out var retryAfterValue)
            ? ReadNullableNumber(retryAfterValue, "retry_after_s")
            : null;
        var httpStatus = failure.TryGetValue("http_status", out var statusValue)
            ? ReadNullableInt32(statusValue, "http_status")
            : null;
        var phase = failure.TryGetValue("phase", out var phaseValue)
            ? ReadNullableString(phaseValue, "phase")
            : DefaultPhase(category);
        return new ScriptFailure(category, retryable, retryAfter, httpStatus, phase);
    }

    private static ProviderException CreateProviderException(ScriptFailure failure) => new(
        "Fixture adapter scripted failure.",
        failure.Category,
        failure.Retryable,
        failure.Phase,
        failure.RetryAfterSeconds,
        failure.HttpStatus,
        provider: "fixture");

    private static bool DefaultRetryable(string category) => category switch
    {
        "rate_limit" or "transport" or "provider_unavailable" => true,
        _ => false,
    };

    private static string? DefaultPhase(string category) => category switch
    {
        "stream_protocol" => "stream",
        _ => "generate",
    };

    private static Usage? ReadUsage(JsonValue value)
    {
        if (value is JsonNull)
        {
            return null;
        }

        if (value is not JsonObject usage)
        {
            throw new InvalidOperationException("Fixture adapter usage must be an object or null.");
        }

        return new Usage(
            ReadOptionalInt64(usage, "input_tokens"),
            ReadOptionalInt64(usage, "output_tokens"),
            ReadOptionalInt64(usage, "total_tokens"),
            ReadOptionalInt64(usage, "cache_read_tokens"),
            ReadOptionalInt64(usage, "cache_write_tokens"),
            ReadOptionalInt64(usage, "reasoning_tokens"));
    }

    private static long? ReadOptionalInt64(JsonObject value, string property) =>
        value.TryGetValue(property, out var item) ? ReadNullableInt64(item, property) : null;

    private static long? ReadNullableInt64(JsonValue value, string property)
    {
        if (value is JsonNull)
        {
            return null;
        }

        if (value is JsonInteger integer && integer.Value >= long.MinValue && integer.Value <= long.MaxValue)
        {
            return (long)integer.Value;
        }

        throw new InvalidOperationException($"Fixture adapter {property} must be an integer or null.");
    }

    private static int? ReadNullableInt32(JsonValue value, string property)
    {
        var number = ReadNullableInt64(value, property);
        if (number is null)
        {
            return null;
        }

        if (number < int.MinValue || number > int.MaxValue)
        {
            throw new InvalidOperationException($"Fixture adapter {property} is outside Int32 range.");
        }

        return (int)number.Value;
    }

    private static double? ReadNullableNumber(JsonValue value, string property) => value switch
    {
        JsonNull => null,
        JsonInteger integer => (double)integer.Value,
        JsonNumber number => number.Value,
        _ => throw new InvalidOperationException($"Fixture adapter {property} must be a number or null."),
    };

    private static bool ReadBoolean(JsonValue value, string property) => value is JsonBoolean boolean
        ? boolean.Value
        : throw new InvalidOperationException($"Fixture adapter {property} must be a boolean.");

    private static string ReadString(JsonValue value, string property) => value is JsonString text
        ? text.Value
        : throw new InvalidOperationException($"Fixture adapter {property} must be a string.");

    private static string? ReadNullableString(JsonValue value, string property) => value switch
    {
        JsonNull => null,
        JsonString text => text.Value,
        _ => throw new InvalidOperationException($"Fixture adapter {property} must be a string or null."),
    };

    private void ThrowIfDisposed()
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            throw new ObjectDisposedException(nameof(FixtureAdapter));
        }
    }

    private sealed record ScriptFailure(
        string Category,
        bool Retryable,
        double? RetryAfterSeconds,
        int? HttpStatus,
        string? Phase);

    private enum FailureLocation
    {
        Entry,
        Terminal,
        Cleanup,
    }
}

/// <summary>Checks the closed script envelope shared by released fixtures and direct adapter tests.</summary>
internal static class FixtureScriptValidation
{
    private static readonly HashSet<string> FailureMembers = new(StringComparer.Ordinal)
    {
        "category", "retryable", "retry_after_s", "http_status", "phase",
    };

    private static readonly HashSet<string> FailureCategories = new(StringComparer.Ordinal)
    {
        "auth", "rate_limit", "transport", "provider_unavailable", "model_not_found",
        "context_length", "stream_protocol", "unsupported_input",
    };

    private static readonly HashSet<string> Phases = new(StringComparer.Ordinal)
    {
        "configure", "discover", "generate", "stream", "validate", "cleanup",
    };

    private static readonly HashSet<string> FinishReasons = new(StringComparer.Ordinal)
    {
        "stop", "length", "tool_calls", "content_filter", "other",
    };

    internal static void ValidateScript(JsonArray script)
    {
        ArgumentNullException.ThrowIfNull(script);
        foreach (var entry in script.Items)
        {
            if (entry is not JsonObject objectEntry)
            {
                throw new InvalidOperationException("Fixture adapter script entry must be an object.");
            }

            ValidateEntry(objectEntry);
        }
    }

    private static void ValidateEntry(JsonObject entry)
    {
        var hasFail = entry.TryGetValue("fail", out var fail);
        var hasEvents = entry.TryGetValue("events", out var eventsValue);
        var hasCleanup = entry.TryGetValue("fail_in_cleanup", out var cleanup);
        EnsureKeys(entry, "fail", "events", "fail_in_cleanup");
        if (hasFail && !hasEvents && !hasCleanup)
        {
            ValidateFailure(fail!);
            return;
        }

        if (!hasEvents || hasCleanup && hasFail)
        {
            throw new InvalidOperationException("Fixture adapter script entry has an invalid action shape.");
        }

        if (eventsValue is not JsonArray events)
        {
            throw new InvalidOperationException("Fixture adapter events must be an array.");
        }

        var finalSeen = false;
        foreach (var item in events.Items)
        {
            finalSeen |= ValidateEvent(item);
        }

        if (hasFail)
        {
            ValidateFailure(fail!);
        }

        if (hasCleanup)
        {
            if (!finalSeen)
            {
                throw new InvalidOperationException("Fixture cleanup failure requires a final event.");
            }

            ValidateFailure(cleanup!);
        }
    }

    private static bool ValidateEvent(JsonValue value)
    {
        if (value is not JsonObject item || item.Properties.Count != 1)
        {
            throw new InvalidOperationException("Fixture adapter event must have exactly one action.");
        }

        var property = item.Properties[0];
        switch (property.Name)
        {
            case "text":
                RequireString(property.Value, "text");
                return false;
            case "usage":
                ValidateUsage(property.Value);
                return false;
            case "await_release":
                if (RequireString(property.Value, "await_release").Length == 0)
                {
                    throw new InvalidOperationException("Fixture await_release cannot be empty.");
                }

                return false;
            case "final":
                ValidateFinal(property.Value);
                return true;
            default:
                throw new InvalidOperationException("Fixture adapter event action is unsupported.");
        }
    }

    private static void ValidateFinal(JsonValue value)
    {
        if (value is not JsonObject final)
        {
            throw new InvalidOperationException("Fixture final event must be an object.");
        }

        EnsureKeys(final, "finish_reason", "usage");
        if (final.TryGetValue("finish_reason", out var reason) && !FinishReasons.Contains(RequireString(reason, "finish_reason")))
        {
            throw new InvalidOperationException("Fixture finish reason is unsupported.");
        }

        if (final.TryGetValue("usage", out var usage))
        {
            ValidateUsage(usage);
        }
    }

    private static void ValidateUsage(JsonValue value)
    {
        if (value is JsonNull)
        {
            return;
        }

        if (value is not JsonObject usage)
        {
            throw new InvalidOperationException("Fixture usage must be an object or null.");
        }

        EnsureKeys(usage, "input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens");
        foreach (var property in usage.Properties)
        {
            if (property.Value is not JsonNull && property.Value is not JsonInteger)
            {
                throw new InvalidOperationException("Fixture usage values must be integers or null.");
            }
        }
    }

    private static void ValidateFailure(JsonValue value)
    {
        if (value is not JsonObject failure || !failure.TryGetValue("category", out var categoryValue))
        {
            throw new InvalidOperationException("Fixture failure requires category.");
        }

        EnsureKeys(failure, "category", "retryable", "retry_after_s", "http_status", "phase");
        if (!FailureCategories.Contains(RequireString(categoryValue, "category")))
        {
            throw new InvalidOperationException("Fixture failure category is unsupported.");
        }

        if (failure.TryGetValue("retryable", out var retryable) && retryable is not JsonBoolean)
        {
            throw new InvalidOperationException("Fixture failure retryable must be a boolean.");
        }

        if (failure.TryGetValue("retry_after_s", out var retryAfter) && retryAfter is not JsonNull and not JsonInteger and not JsonNumber)
        {
            throw new InvalidOperationException("Fixture failure retry_after_s must be a number or null.");
        }

        if (failure.TryGetValue("http_status", out var status) && status is not JsonNull and not JsonInteger)
        {
            throw new InvalidOperationException("Fixture failure http_status must be an integer or null.");
        }

        if (failure.TryGetValue("phase", out var phase) && phase is not JsonNull && (!TryString(phase, out var name) || !Phases.Contains(name)))
        {
            throw new InvalidOperationException("Fixture failure phase is unsupported.");
        }
    }

    private static void EnsureKeys(JsonObject value, params string[] allowed)
    {
        foreach (var property in value.Properties)
        {
            if (!allowed.Contains(property.Name, StringComparer.Ordinal))
            {
                throw new InvalidOperationException("Fixture script object contains an unrecognized member.");
            }
        }
    }

    private static string RequireString(JsonValue value, string name) => value is JsonString text
        ? text.Value
        : throw new InvalidOperationException($"Fixture {name} must be a string.");

    private static bool TryString(JsonValue value, out string text)
    {
        if (value is JsonString stringValue)
        {
            text = stringValue.Value;
            return true;
        }

        text = string.Empty;
        return false;
    }
}

/// <summary>Coordinates named fixture script pauses without exposing a library API.</summary>
internal sealed class FixtureGates
{
    private readonly ConcurrentDictionary<string, TaskCompletionSource> _gates = new(StringComparer.Ordinal);

    internal Task WaitAsync(string name, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        var gate = _gates.GetOrAdd(name, static _ => new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously));
        return gate.Task.WaitAsync(cancellationToken);
    }

    internal void Release(string name)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        var gate = _gates.GetOrAdd(name, static _ => new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously));
        gate.TrySetResult();
    }
}
