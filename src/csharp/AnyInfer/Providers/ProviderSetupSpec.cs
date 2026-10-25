using System.Collections.ObjectModel;

namespace AnyInfer.Providers;

/// <summary>Declarative metadata for one provider setup field.</summary>
/// <remarks>
/// Setup metadata is inert: it describes what an application's configuration surface should ask for and
/// never resolves secrets or reads environment variables itself.
/// </remarks>
public sealed record SetupField
{
    private static readonly ISet<string> KnownKinds = new HashSet<string>(StringComparer.Ordinal)
    {
        "endpoint", "secret", "api-version", "model-list", "reasoning-efforts", "host-profile", "text", "choice", "path", "directory",
    };

    /// <summary>Creates validated setup-field metadata.</summary>
    /// <param name="key">Stable configuration key, such as <c>base_url</c> or <c>api_key</c>.</param>
    /// <param name="label">Human-readable label.</param>
    /// <param name="kind">
    /// Value kind: <c>endpoint</c>, <c>secret</c>, <c>api-version</c>, <c>model-list</c>, <c>reasoning-efforts</c>,
    /// <c>host-profile</c>, <c>text</c>, <c>choice</c>, <c>path</c>, or <c>directory</c>.
    /// </param>
    /// <param name="required">Whether a value must be supplied; a required field cannot be advanced.</param>
    /// <param name="helpText">User guidance, or <see langword="null"/> for none.</param>
    /// <param name="placeholder">Placeholder text for an input control, or <see langword="null"/> for none.</param>
    /// <param name="envVar">Bare environment-variable name to suggest, or <see langword="null"/>; never a <c>scheme://</c> reference or a secret.</param>
    /// <param name="advanced">Whether this optional field belongs with advanced settings.</param>
    /// <param name="defaultValue">Default value, or <see langword="null"/>; only advanced fields may declare one.</param>
    /// <param name="choices">Allowed values for a <c>choice</c> field, unique and copied in order; other kinds must declare none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="key"/> or <paramref name="label"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="key"/> or <paramref name="label"/> is empty, <paramref name="kind"/> is unsupported, or the
    /// field combines settings that are not allowed together, as described for each parameter.
    /// </exception>
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

        helpText ??= "";
        placeholder ??= "";
        envVar ??= "";
        defaultValue ??= "";

        if (defaultValue.Length != 0 && !advanced)
        {
            throw new ArgumentException("A setup field with a default value must be advanced.", nameof(defaultValue));
        }

        if (envVar.Length != 0 && (envVar != envVar.Trim() || envVar.Contains("://", StringComparison.Ordinal)))
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

        if (defaultValue.Length != 0 && kind == "choice" && !copiedChoices.Contains(defaultValue, StringComparer.Ordinal))
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
    public string HelpText { get; }
    /// <summary>Gets optional UI placeholder text.</summary>
    public string Placeholder { get; }
    /// <summary>Gets an optional bare environment-variable hint, never a resolved secret.</summary>
    public string EnvVar { get; }
    /// <summary>Gets whether this optional field is advanced.</summary>
    public bool Advanced { get; }
    /// <summary>Gets the optional advanced default value.</summary>
    public string DefaultValue { get; }
    /// <summary>Gets immutable choices for a choice field.</summary>
    public IReadOnlyList<string> Choices { get; }
}

/// <summary>Expansion rule for bare host names entered as provider base URLs.</summary>
public sealed record HostShorthand
{
    /// <summary>Initializes a bare-host expansion rule.</summary>
    /// <param name="scheme">URL scheme to prepend, such as <c>http</c>.</param>
    /// <param name="defaultPort">Port to append when the host names none.</param>
    /// <exception cref="ArgumentNullException"><paramref name="scheme"/> is <see langword="null"/>.</exception>
    public HostShorthand(string scheme, int defaultPort)
    {
        ArgumentNullException.ThrowIfNull(scheme);
        Scheme = scheme;
        DefaultPort = defaultPort;
    }

    /// <summary>Gets the URL scheme prepended to bare hosts.</summary>
    public string Scheme { get; }
    /// <summary>Gets the port appended when a bare host has no port before its first path separator.</summary>
    public int DefaultPort { get; }

    /// <summary>Expands a bare host while preserving explicit URLs and ports through literal string rules.</summary>
    /// <param name="host">Host text; surrounding whitespace is removed.</param>
    /// <returns>
    /// The trimmed text unchanged when it contains <c>://</c>; otherwise the scheme prepended, plus
    /// <see cref="DefaultPort"/> when the part before the first <c>/</c> has no <c>:</c>. The result is not validated as a URL.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="host"/> is <see langword="null"/>.</exception>
    public string Expand(string host)
    {
        ArgumentNullException.ThrowIfNull(host);
        var value = host.Trim();
        if (value.Contains("://", StringComparison.Ordinal))
        {
            return value;
        }

        var firstSlash = value.IndexOf('/');
        var authority = firstSlash < 0 ? value : value[..firstSlash];
        return authority.Contains(':', StringComparison.Ordinal)
            ? $"{Scheme}://{value}"
            : $"{Scheme}://{value}:{DefaultPort}";
    }
}

/// <summary>Declarative provider setup metadata used by configuration and UI callers.</summary>
public sealed record ProviderSetupSpec
{
    /// <summary>Initializes declarative provider setup metadata.</summary>
    /// <param name="fields">Setup fields in display order, with unique keys; <see langword="null"/> means none.</param>
    /// <param name="modelSelection">
    /// <c>discover-or-manual</c> when models may be discovered or typed, or <c>manual-only</c> when they must be typed.
    /// </param>
    /// <param name="hostShorthand">Bare-host expansion rule for base URLs, or <see langword="null"/> for none.</param>
    /// <param name="anyOf">
    /// Groups of field keys of which at least one must have a value; advanced fields cannot appear in a group.
    /// <see langword="null"/> means none.
    /// </param>
    /// <param name="requirementNote">Provider-authored explanation of the setup requirements; <see langword="null"/> is treated as empty.</param>
    /// <exception cref="ArgumentNullException">A group in <paramref name="anyOf"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// Fields contain <see langword="null"/> or repeat a key, <paramref name="modelSelection"/> is unsupported, a group
    /// contains a <see langword="null"/> key, or an advanced field appears in a group.
    /// </exception>
    public ProviderSetupSpec(
        IEnumerable<SetupField>? fields = null,
        string modelSelection = "discover-or-manual",
        HostShorthand? hostShorthand = null,
        IEnumerable<IEnumerable<string>>? anyOf = null,
        string requirementNote = "")
    {
        var copied = (fields ?? []).Select(static field => field ?? throw new ArgumentException("Setup fields cannot contain null values.")).ToArray();
        if (copied.Select(static field => field.Key).Distinct(StringComparer.Ordinal).Count() != copied.Length)
        {
            throw new ArgumentException("Setup field keys must be unique.", nameof(fields));
        }

        if (modelSelection != "discover-or-manual" && modelSelection != "manual-only")
        {
            throw new ArgumentException("The setup model-selection mode is not supported.", nameof(modelSelection));
        }

        var copiedGroups = (anyOf ?? []).Select(group =>
        {
            ArgumentNullException.ThrowIfNull(group);
            var keys = group.Select(static key => key ?? throw new ArgumentException("Any-of groups cannot contain null keys.", nameof(anyOf))).ToArray();
            return (IReadOnlyList<string>)Array.AsReadOnly(keys);
        }).ToArray();
        var blocking = copiedGroups.SelectMany(static group => group).ToHashSet(StringComparer.Ordinal);
        if (copied.Any(field => field.Advanced && blocking.Contains(field.Key)))
        {
            throw new ArgumentException("Advanced setup fields cannot occur in any-of groups.", nameof(anyOf));
        }

        Fields = Array.AsReadOnly(copied);
        ModelSelection = modelSelection;
        HostShorthand = hostShorthand;
        AnyOf = Array.AsReadOnly(copiedGroups);
        RequirementNote = requirementNote ?? "";
    }

    /// <summary>Gets immutable field metadata in declared order.</summary>
    public IReadOnlyList<SetupField> Fields { get; }
    /// <summary>Gets the bounded model-selection mode.</summary>
    public string ModelSelection { get; }
    /// <summary>Gets the optional bare-host expansion rule.</summary>
    public HostShorthand? HostShorthand { get; }
    /// <summary>Gets immutable groups for which at least one field key must have a value.</summary>
    public IReadOnlyList<IReadOnlyList<string>> AnyOf { get; }
    /// <summary>Gets the provider-authored explanation for setup requirements.</summary>
    public string RequirementNote { get; }
    /// <summary>Gets non-advanced setup fields in declared order.</summary>
    public IReadOnlyList<SetupField> EssentialFields => Array.AsReadOnly(Fields.Where(static field => !field.Advanced).ToArray());
    /// <summary>Gets advanced setup fields in declared order.</summary>
    public IReadOnlyList<SetupField> AdvancedFields => Array.AsReadOnly(Fields.Where(static field => field.Advanced).ToArray());

    /// <summary>Returns groups for which none of the declared keys has a non-blank value.</summary>
    /// <param name="values">Candidate setup values keyed by field key.</param>
    /// <returns>The unsatisfied <see cref="AnyOf"/> groups in declared order; empty when every group is satisfied.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="values"/> is <see langword="null"/>.</exception>
    public IReadOnlyList<IReadOnlyList<string>> UnsatisfiedGroups(IReadOnlyDictionary<string, string> values)
    {
        ArgumentNullException.ThrowIfNull(values);
        return Array.AsReadOnly(AnyOf.Where(group => !group.Any(key =>
            values.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value))).ToArray());
    }

    /// <summary>Returns a declared field label, or the supplied key when no field has that exact key.</summary>
    /// <param name="key">Exact, case-sensitive field key.</param>
    /// <returns>The field's label, or <paramref name="key"/> itself when no field matches.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="key"/> is <see langword="null"/>.</exception>
    public string LabelFor(string key)
    {
        ArgumentNullException.ThrowIfNull(key);
        return Fields.FirstOrDefault(field => string.Equals(field.Key, key, StringComparison.Ordinal))?.Label ?? key;
    }
}
