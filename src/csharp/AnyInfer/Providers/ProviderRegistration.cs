using System.Collections.ObjectModel;

namespace AnyInfer.Providers;

/// <summary>Declares one adapter and its model-specific structured-output capabilities.</summary>
public sealed record ProviderRegistration
{
    /// <summary>Creates an immutable provider registration.</summary>
    public ProviderRegistration(
        string providerId,
        IAsyncDisposable adapter,
        IReadOnlyDictionary<string, StructuredOutputProfile>? structuredOutputProfiles = null,
        int? maxRepairAttempts = null)
    {
        if (string.IsNullOrWhiteSpace(providerId))
        {
            throw new ArgumentException("Provider ID cannot be empty.", nameof(providerId));
        }

        if (maxRepairAttempts is < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxRepairAttempts));
        }

        ProviderId = providerId;
        Adapter = adapter ?? throw new ArgumentNullException(nameof(adapter));
        var copied = new Dictionary<string, StructuredOutputProfile>(StringComparer.Ordinal);
        if (structuredOutputProfiles is not null)
        {
            foreach (var (model, profile) in structuredOutputProfiles)
            {
                if (model is null)
                {
                    throw new ArgumentException("Model capability keys cannot be null.", nameof(structuredOutputProfiles));
                }

                copied.Add(model, profile ?? throw new ArgumentException("Model capability values cannot be null.", nameof(structuredOutputProfiles)));
            }
        }

        StructuredOutputProfiles = new ReadOnlyDictionary<string, StructuredOutputProfile>(copied);
        MaxRepairAttempts = maxRepairAttempts;
    }

    /// <summary>Gets the exact v0 provider ID.</summary>
    public string ProviderId { get; }

    /// <summary>Gets the adapter owned by this registration.</summary>
    public IAsyncDisposable Adapter { get; }

    /// <summary>Gets immutable capabilities keyed by exact resolved model name.</summary>
    public IReadOnlyDictionary<string, StructuredOutputProfile> StructuredOutputProfiles { get; }

    /// <summary>Gets the optional provider repair ceiling.</summary>
    public int? MaxRepairAttempts { get; }
}

/// <summary>Describes structured-output mechanisms supported by one exact model.</summary>
public sealed record StructuredOutputProfile(bool Grammar = false, bool JsonSchema = false, bool JsonMode = false);
