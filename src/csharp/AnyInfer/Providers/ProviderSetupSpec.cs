using System.Collections.ObjectModel;

namespace AnyInfer.Providers;

/// <summary>Declarative metadata for one provider setup field.</summary>
public sealed record SetupField
{
    private static readonly ISet<string> KnownKinds = new HashSet<string>(StringComparer.Ordinal)
    {
        "endpoint", "secret", "api-version", "model-list", "reasoning-efforts", "host-profile", "text", "choice", "path", "directory",
    };

    public SetupField(
        string key,
        string label,
        string kind = "text",
        bool required = false,
        string? helpText = null,
        string? placeholder = null,
        string? envVar = null,
        bool advanced = false,
        string? defaultValue = null,
        IEnumerable<string>? choices = null)
    {
        ArgumentException.ThrowIfNullOrEmpty(key);
        ArgumentException.ThrowIfNullOrEmpty(label);
        if (!KnownKinds.Contains(kind))
        {
            throw new ArgumentException("The setup field kind is not supported.", nameof(kind));
        }

        if (required && advanced)
        {
            throw new ArgumentException("A required setup field cannot be advanced.", nameof(advanced));
        }

        if (defaultValue is not null && !advanced)
        {
            throw new ArgumentException("A setup field with a default value must be advanced.", nameof(defaultValue));
        }

        if (envVar is not null && (envVar.Length == 0 || envVar != envVar.Trim() || envVar.Contains("://", StringComparison.Ordinal)))
        {
            throw new ArgumentException("Environment-variable hints must be bare names.", nameof(envVar));
        }

        var copiedChoices = (choices ?? []).Select(static choice => choice ?? throw new ArgumentException("Setup choices cannot contain null values.")).ToArray();
        if (kind == "choice" && copiedChoices.Length == 0)
        {
            throw new ArgumentException("Choice setup fields require choices.", nameof(choices));
        }

        if (kind != "choice" && copiedChoices.Length != 0)
        {
            throw new ArgumentException("Only choice setup fields may declare choices.", nameof(choices));
        }

        if (copiedChoices.Distinct(StringComparer.Ordinal).Count() != copiedChoices.Length)
        {
            throw new ArgumentException("Setup choices must be unique.", nameof(choices));
        }

        if (defaultValue is not null && kind == "choice" && !copiedChoices.Contains(defaultValue, StringComparer.Ordinal))
        {
            throw new ArgumentException("Choice defaults must be one of the declared choices.", nameof(defaultValue));
        }

        Key = key;
        Label = label;
        Kind = kind;
        Required = required;
        HelpText = helpText;
        Placeholder = placeholder;
        EnvVar = envVar;
        Advanced = advanced;
        DefaultValue = defaultValue;
        Choices = Array.AsReadOnly(copiedChoices);
    }

    /// <summary>Gets the stable configuration key.</summary>
    public string Key { get; }
    /// <summary>Gets the human-readable configuration label.</summary>
    public string Label { get; }
    /// <summary>Gets the declared setup value kind.</summary>
    public string Kind { get; }
    /// <summary>Gets whether this field must be supplied before construction.</summary>
    public bool Required { get; }
    /// <summary>Gets optional user guidance.</summary>
    public string? HelpText { get; }
    /// <summary>Gets optional UI placeholder text.</summary>
    public string? Placeholder { get; }
    /// <summary>Gets an optional bare environment-variable hint, never a resolved secret.</summary>
    public string? EnvVar { get; }
    /// <summary>Gets whether this optional field is advanced.</summary>
    public bool Advanced { get; }
    /// <summary>Gets the optional advanced default value.</summary>
    public string? DefaultValue { get; }
    /// <summary>Gets immutable choices for a choice field.</summary>
    public IReadOnlyList<string> Choices { get; }
}

/// <summary>Declarative provider setup metadata used by configuration and UI callers.</summary>
public sealed record ProviderSetupSpec
{
    public ProviderSetupSpec(IEnumerable<SetupField>? fields = null, string modelSelection = "manual-only")
    {
        var copied = (fields ?? []).Select(static field => field ?? throw new ArgumentException("Setup fields cannot contain null values.")).ToArray();
        if (copied.Select(static field => field.Key).Distinct(StringComparer.Ordinal).Count() != copied.Length)
        {
            throw new ArgumentException("Setup field keys must be unique.", nameof(fields));
        }

        if (modelSelection != "manual-only")
        {
            throw new ArgumentException("Only manual model selection is available in this SDK phase.", nameof(modelSelection));
        }

        Fields = Array.AsReadOnly(copied);
        ModelSelection = modelSelection;
    }

    /// <summary>Gets immutable field metadata in declared order.</summary>
    public IReadOnlyList<SetupField> Fields { get; }
    /// <summary>Gets the bounded model-selection mode.</summary>
    public string ModelSelection { get; }
}
