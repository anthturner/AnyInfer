using AnyInfer.Json;

namespace AnyInfer;

/// <summary>Untrusted provider-facing hints about a tool declaration.</summary>
/// <remarks>These metadata hints confer no permission and must not authorize execution.</remarks>
public sealed record ToolAnnotations
{
    /// <summary>Creates immutable optional tool annotations.</summary>
    /// <param name="title">Optional display title. An empty value is still explicitly stated.</param>
    /// <param name="readOnly">Optional read-only hint.</param>
    /// <param name="destructive">Optional destructive-operation hint.</param>
    /// <param name="idempotent">Optional idempotence hint.</param>
    /// <param name="openWorld">Optional open-world-effect hint.</param>
    public ToolAnnotations(
        string? title = null,
        bool? readOnly = null,
        bool? destructive = null,
        bool? idempotent = null,
        bool? openWorld = null)
    {
        Title = title;
        ReadOnly = readOnly;
        Destructive = destructive;
        Idempotent = idempotent;
        OpenWorld = openWorld;
    }

    /// <summary>Gets the optional display title.</summary>
    public string? Title { get; }
    /// <summary>Gets the optional read-only hint.</summary>
    public bool? ReadOnly { get; }
    /// <summary>Gets the optional destructive-operation hint.</summary>
    public bool? Destructive { get; }
    /// <summary>Gets the optional idempotence hint.</summary>
    public bool? Idempotent { get; }
    /// <summary>Gets the optional open-world-effect hint.</summary>
    public bool? OpenWorld { get; }
    /// <summary>Gets whether any annotation was explicitly supplied, including false or an empty title.</summary>
    public bool Stated => Title is not null || ReadOnly is not null || Destructive is not null || Idempotent is not null || OpenWorld is not null;
}

/// <summary>Immutable declaration of a provider-callable function tool.</summary>
public sealed record ToolSpec
{
    /// <summary>Creates a tool declaration without interpreting its parameter schema.</summary>
    /// <param name="name">Provider-visible tool name.</param>
    /// <param name="description">Provider-visible description.</param>
    /// <param name="parameters">Tagged JSON parameter schema.</param>
    /// <param name="annotations">Optional untrusted metadata hints.</param>
    public ToolSpec(string name, string description, JsonObject parameters, ToolAnnotations? annotations = null)
    {
        Name = name ?? throw new ArgumentNullException(nameof(name));
        Description = description ?? throw new ArgumentNullException(nameof(description));
        Parameters = parameters ?? throw new ArgumentNullException(nameof(parameters));
        Annotations = annotations ?? new ToolAnnotations();
    }

    /// <summary>Gets the provider-visible name.</summary>
    public string Name { get; }
    /// <summary>Gets the provider-visible description.</summary>
    public string Description { get; }
    /// <summary>Gets the immutable tagged JSON parameter schema.</summary>
    public JsonObject Parameters { get; }
    /// <summary>Gets untrusted annotations, empty when none were supplied.</summary>
    public ToolAnnotations Annotations { get; }
}
