using AnyInfer.Capabilities;

namespace AnyInfer.Providers;

/// <summary>Source-only compatibility facts that do not constitute native support claims.</summary>
internal sealed record CompatPresetSourceFacts
{
    internal CompatPresetSourceFacts(
        string id,
        IEnumerable<string> sourceOperations,
        bool sourceHonorsConnectionSettings,
        string sourceModelInventory,
        IEnumerable<string> contractDependencies,
        string sourceFactoryTarget)
    {
        Id = ProviderSettings.NormalizeId(id, nameof(id));
        SourceOperations = CopySourceOperations(sourceOperations);
        if (!sourceHonorsConnectionSettings)
        {
            throw new ArgumentException("Compatibility preset source facts must retain connection-settings support.", nameof(sourceHonorsConnectionSettings));
        }

        if (!string.Equals(sourceModelInventory, "served", StringComparison.Ordinal))
        {
            throw new ArgumentException("Compatibility preset source facts must retain served model inventory.", nameof(sourceModelInventory));
        }

        SourceHonorsConnectionSettings = true;
        SourceModelInventory = sourceModelInventory;
        ContractDependencies = Copy(contractDependencies, nameof(contractDependencies));
        ArgumentException.ThrowIfNullOrEmpty(sourceFactoryTarget);
        SourceFactoryTarget = sourceFactoryTarget;
    }

    internal string Id { get; }

    internal IReadOnlyList<string> SourceOperations { get; }

    internal bool SourceHonorsConnectionSettings { get; }

    internal string SourceModelInventory { get; }

    internal IReadOnlyList<string> ContractDependencies { get; }

    internal string SourceFactoryTarget { get; }

    private static IReadOnlyList<string> CopySourceOperations(IEnumerable<string> sourceOperations)
    {
        ArgumentNullException.ThrowIfNull(sourceOperations);
        var copied = sourceOperations
            .Select(static operation => operation ?? throw new ArgumentException("Source operations cannot contain null values.", nameof(sourceOperations)))
            .ToArray();
        var valid = new HashSet<string>(StringComparer.Ordinal)
        {
            "generation", "embedding", "rerank", "batch",
        };
        if (copied.Length == 0 ||
            copied.Any(operation => !valid.Contains(operation)) ||
            copied.Distinct(StringComparer.Ordinal).Count() != copied.Length ||
            !copied.Contains("generation", StringComparer.Ordinal))
        {
            throw new ArgumentException("Source operations must be unique known values that include generation.", nameof(sourceOperations));
        }

        return Array.AsReadOnly(copied.OrderBy(static operation => operation, StringComparer.Ordinal).ToArray());
    }

    private static IReadOnlyList<string> Copy(IEnumerable<string> values, string parameterName)
    {
        ArgumentNullException.ThrowIfNull(values);
        return Array.AsReadOnly(values
            .Select(value => value ?? throw new ArgumentException("Compatibility preset values cannot contain null references.", parameterName))
            .ToArray());
    }
}

/// <summary>Generation-only native projection for one compatibility-preset source row.</summary>
internal sealed record CompatPresetGenerationRow
{
    internal CompatPresetGenerationRow(
        string id,
        string displayName,
        IEnumerable<string> aliases,
        string? defaultBaseUrl,
        bool requiresBaseUrl,
        ProviderLocality locality,
        ProviderSetupSpec setup,
        ModelCapabilities defaultCapabilities,
        IEnumerable<string> ignoredParameters,
        OpenAICompatDialectOptions dialect,
        CompatPresetReasoningStyle reasoningStyle,
        IEnumerable<InferenceOperation> implementedOperations)
    {
        ArgumentNullException.ThrowIfNull(setup);
        ArgumentNullException.ThrowIfNull(defaultCapabilities);
        ArgumentNullException.ThrowIfNull(dialect);
        if (!Enum.IsDefined(locality))
        {
            throw new ArgumentOutOfRangeException(nameof(locality));
        }

        if (!Enum.IsDefined(reasoningStyle))
        {
            throw new ArgumentOutOfRangeException(nameof(reasoningStyle));
        }

        var operations = CopyOperations(implementedOperations);
        var copiedAliases = Copy(aliases, nameof(aliases));
        var copiedIgnoredParameters = Copy(ignoredParameters, nameof(ignoredParameters));
        Descriptor = new ProviderDescriptor(
            id,
            displayName,
            (config, cancellationToken) => new ValueTask<IAsyncDisposable>(
                OpenAIChatAdapter.Create(config, dialect, cancellationToken)),
            aliases: copiedAliases,
            setup: setup,
            defaultBaseUrl: defaultBaseUrl,
            requiresBaseUrl: requiresBaseUrl,
            locality: locality,
            defaultCapabilities: defaultCapabilities,
            operations: operations,
            reasoningTranslator: effort => CompatPresetReasoning.Translate(reasoningStyle, effort),
            ignoredParameters: copiedIgnoredParameters)
        {
            PoolOwnsConfiguredTransport = true,
        };
        Dialect = dialect;
        ReasoningStyle = reasoningStyle;
    }

    internal ProviderDescriptor Descriptor { get; }

    internal OpenAICompatDialectOptions Dialect { get; }

    internal CompatPresetReasoningStyle ReasoningStyle { get; }

    private static IReadOnlyList<InferenceOperation> CopyOperations(IEnumerable<InferenceOperation> operations)
    {
        ArgumentNullException.ThrowIfNull(operations);
        var copied = operations.ToArray();
        if (copied.Length != 1 || copied[0] != InferenceOperation.Generation)
        {
            throw new ArgumentException("Compatibility preset rows implement generation only.", nameof(operations));
        }

        return Array.AsReadOnly(copied);
    }

    private static IReadOnlyList<string> Copy(IEnumerable<string> values, string parameterName)
    {
        ArgumentNullException.ThrowIfNull(values);
        return Array.AsReadOnly(values
            .Select(value => value ?? throw new ArgumentException("Compatibility preset values cannot contain null references.", parameterName))
            .ToArray());
    }
}

/// <summary>Joins source-only facts to an inert native generation descriptor.</summary>
internal sealed record CompatPresetDefinition
{
    internal CompatPresetDefinition(CompatPresetSourceFacts source, CompatPresetGenerationRow generation)
    {
        Source = source ?? throw new ArgumentNullException(nameof(source));
        Generation = generation ?? throw new ArgumentNullException(nameof(generation));
        if (!string.Equals(Source.Id, Generation.Descriptor.Id, StringComparison.Ordinal))
        {
            throw new ArgumentException("Compatibility preset source and generation IDs must agree.", nameof(generation));
        }

        PendingNativeParity = Array.AsReadOnly(new[] { "connection-settings", "model-inventory" });
    }

    internal CompatPresetSourceFacts Source { get; }

    internal CompatPresetGenerationRow Generation { get; }

    internal IReadOnlyList<string> PendingNativeParity { get; }
}

/// <summary>Generated compatibility-preset metadata; intentionally separate from the default registry.</summary>
internal static partial class CompatPresetTable
{
}
