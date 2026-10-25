using System.Collections.ObjectModel;

namespace AnyInfer.Providers;

/// <summary>Declares one adapter and its model-specific structured-output capabilities.</summary>
/// <remarks>
/// Registrations supply already-constructed adapters to <see cref="AsyncClient.FromAdapters"/> or
/// <see cref="Client.FromAdapters"/> instead of settings and descriptors. The client takes ownership of each
/// adapter and disposes it when the client is disposed.
/// </remarks>
public sealed record ProviderRegistration
{
    /// <summary>Creates an immutable provider registration.</summary>
    /// <param name="providerId">Instance identifier used as the provider part of <c>provider:model</c> targets; the client normalizes it and requires it to be unique.</param>
    /// <param name="adapter">
    /// Adapter instance, implementing <see cref="IGeneratesText"/>, <see cref="IEmbedsText"/>, or
    /// <see cref="IReranksText"/> for each operation it serves; using an operation the adapter does not implement
    /// fails with <see cref="ConfigException"/>.
    /// </param>
    /// <param name="structuredOutputProfiles">
    /// Native structured-output mechanisms keyed by exact model name, copied; a model without a row uses
    /// prompt-based structured output. <see langword="null"/> means none.
    /// </param>
    /// <param name="maxRepairAttempts">Ceiling on structured-output repair round trips, or <see langword="null"/> for none.</param>
    /// <exception cref="ArgumentException">
    /// <paramref name="providerId"/> is <see langword="null"/>, empty, or whitespace, or
    /// <paramref name="structuredOutputProfiles"/> contains a <see langword="null"/> key or value.
    /// </exception>
    /// <exception cref="ArgumentNullException"><paramref name="adapter"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="maxRepairAttempts"/> is negative.</exception>
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

    /// <summary>Gets the instance identifier exactly as supplied.</summary>
    public string ProviderId { get; }

    /// <summary>Gets the registered adapter; a client created from this registration owns and disposes it.</summary>
    public IAsyncDisposable Adapter { get; }

    /// <summary>Gets immutable capabilities keyed by exact resolved model name.</summary>
    public IReadOnlyDictionary<string, StructuredOutputProfile> StructuredOutputProfiles { get; }

    /// <summary>Gets the optional provider repair ceiling.</summary>
    public int? MaxRepairAttempts { get; }
}

/// <summary>Describes structured-output mechanisms supported by one exact model.</summary>
/// <remarks>
/// The client prefers grammar, then JSON Schema, then JSON mode, and falls back to prompt-based structured
/// output when none is supported.
/// </remarks>
/// <param name="Grammar">Whether the model supports grammar-constrained output.</param>
/// <param name="JsonSchema">Whether the model supports native JSON Schema output.</param>
/// <param name="JsonMode">Whether the model supports a JSON-only output mode.</param>
public sealed record StructuredOutputProfile(bool Grammar = false, bool JsonSchema = false, bool JsonMode = false);
