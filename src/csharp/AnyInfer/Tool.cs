using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>A caller-authorized tool declaration and its executable handler.</summary>
public sealed class Tool
{
    private readonly Func<JsonObject, CancellationToken, ValueTask<object?>> _handler;

    /// <summary>Creates a tool at the explicit tagged-JSON callback boundary.</summary>
    public Tool(ToolSpec spec, Func<JsonObject, CancellationToken, ValueTask<object?>> handler)
    {
        Spec = spec ?? throw new ArgumentNullException(nameof(spec));
        _handler = handler ?? throw new ArgumentNullException(nameof(handler));
    }

    /// <summary>Gets the declaration advertised to a model.</summary>
    public ToolSpec Spec { get; }

    /// <summary>Gets the provider-visible tool name.</summary>
    public string Name => Spec.Name;

    /// <summary>Invokes the caller-owned handler without converting its failures.</summary>
    public ValueTask<object?> CallAsync(JsonObject arguments, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(arguments);
        return _handler(arguments, cancellationToken);
    }

    /// <summary>Builds a tool declaration and typed binder from a supported delegate signature.</summary>
    public static Tool From(Delegate function, string? name = null, string? description = null) =>
        ToolBinding.Create(function, name, description);
}
