using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer;

/// <summary>A caller-authorized tool declaration and its executable handler.</summary>
public sealed class Tool
{
    private readonly Func<JsonObject, CancellationToken, ValueTask<object?>> _handler;

    /// <summary>Creates a tool at the explicit tagged-JSON callback boundary.</summary>
    /// <param name="spec">The declaration advertised to models. Its parameter schema is not checked against the handler.</param>
    /// <param name="handler">
    /// The caller-owned handler, which receives the model's arguments and the cancellation token of
    /// the call. When the tool runs through <see cref="ToolRegistry.DispatchAsync(ToolCall, CancellationToken)"/>,
    /// a <see langword="null"/> result becomes empty text, a string is used as is, a JSON-shaped
    /// value becomes compact JSON, and any other object uses its <see cref="object.ToString"/> text.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="spec"/> or <paramref name="handler"/> is <see langword="null"/>.</exception>
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
    /// <param name="arguments">The tool arguments as a JSON object.</param>
    /// <param name="cancellationToken">Passed to the handler unchanged.</param>
    /// <returns>The handler's result.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="arguments"/> is <see langword="null"/>.</exception>
    public ValueTask<object?> CallAsync(JsonObject arguments, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(arguments);
        return _handler(arguments, cancellationToken);
    }

    /// <summary>Builds a tool declaration and typed binder from a supported delegate signature.</summary>
    /// <remarks>
    /// <para>
    /// The delegate must have a single, non-generic target method that is not <c>async void</c>.
    /// Each parameter must be <see cref="string"/>, <see cref="bool"/>, <see cref="int"/>,
    /// <see cref="long"/>, <see cref="System.Numerics.BigInteger"/>, <see cref="double"/>,
    /// <see cref="JsonValue"/>, <see cref="JsonObject"/>, <see cref="JsonArray"/> or
    /// <see cref="object"/>, a nullable form of one of these, or a one-dimensional array,
    /// <c>List&lt;T&gt;</c>, <c>IReadOnlyList&lt;T&gt;</c>, <c>Dictionary&lt;string, T&gt;</c> or
    /// <c>IReadOnlyDictionary&lt;string, T&gt;</c> of a supported type. One
    /// <see cref="CancellationToken"/> parameter receives the call's token, and a final
    /// <c>params</c> array always receives an empty array; neither appears in the schema.
    /// <c>ref</c>, <c>out</c> and pointer parameters are rejected.
    /// </para>
    /// <para>
    /// The generated parameter schema is an object with one property per remaining parameter,
    /// lists parameters without default values as required, and sets
    /// <c>additionalProperties</c> to <see langword="false"/>. At call time, unknown or missing
    /// required arguments and values of the wrong JSON type throw <see cref="ArgumentException"/>,
    /// and a returned <see cref="Task"/> or <see cref="ValueTask"/> is awaited.
    /// </para>
    /// </remarks>
    /// <param name="function">The delegate to bind.</param>
    /// <param name="name">
    /// The tool name, or <see langword="null"/> to use the method name; pass a name for lambdas,
    /// whose method names are compiler-generated.
    /// </param>
    /// <param name="description">
    /// The tool description, or <see langword="null"/> to use the method's
    /// <see cref="System.ComponentModel.DescriptionAttribute"/> text, or empty text without one.
    /// </param>
    /// <returns>A tool whose handler binds JSON arguments to the delegate's parameters.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="function"/> is <see langword="null"/>.</exception>
    /// <exception cref="ToolLoopException">The delegate signature is not supported or the tool name is empty.</exception>
    public static Tool From(Delegate function, string? name = null, string? description = null) =>
        ToolBinding.Create(function, name, description);
}
