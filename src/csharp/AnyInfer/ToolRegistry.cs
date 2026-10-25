using System.Threading;
using AnyInfer.Internal;

namespace AnyInfer;

/// <summary>Ordered caller-authorized tools available to one bounded tool loop.</summary>
/// <remarks>
/// The registered tools are fixed at construction; only <see cref="Dispatched"/> changes
/// afterwards, and it is updated atomically.
/// </remarks>
public sealed class ToolRegistry
{
    private readonly Dictionary<string, Tool> _byName = new(StringComparer.Ordinal);
    private readonly IReadOnlyList<ToolSpec> _specs;
    private long _dispatched;

    /// <summary>Registers tools, replacing duplicate names in their first declaration slot.</summary>
    /// <param name="tools">
    /// The tools in declaration order. A later tool whose name, compared ordinally, is already
    /// registered replaces the earlier tool at the earlier tool's position.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="tools"/> or one of its elements is <see langword="null"/>.</exception>
    public ToolRegistry(IEnumerable<Tool> tools)
    {
        ArgumentNullException.ThrowIfNull(tools);
        var ordered = new List<Tool>();
        foreach (var tool in tools)
        {
            ArgumentNullException.ThrowIfNull(tool);
            if (_byName.TryGetValue(tool.Name, out var previous))
            {
                ordered[ordered.IndexOf(previous)] = tool;
            }
            else
            {
                ordered.Add(tool);
            }
            _byName[tool.Name] = tool;
        }
        _specs = Array.AsReadOnly(ordered.Select(static tool => tool.Spec).ToArray());
    }

    /// <summary>Gets immutable tool declarations in surviving insertion order.</summary>
    public IReadOnlyList<ToolSpec> Specs => _specs;

    /// <summary>Gets the count of known dispatches, including failed or cancelled handlers.</summary>
    public long Dispatched => Interlocked.Read(ref _dispatched);

    /// <summary>Dispatches one call, converting ordinary handler failures to a conversational tool result.</summary>
    /// <remarks>
    /// A known tool increments <see cref="Dispatched"/> before its handler runs. The handler's
    /// result is rendered as described for <see cref="Tool(ToolSpec, Func{Json.JsonObject, CancellationToken, ValueTask{object}})"/>.
    /// Any exception other than <see cref="OperationCanceledException"/> becomes an error result
    /// whose content is the exception's type name and message.
    /// </remarks>
    /// <param name="call">The model's tool call.</param>
    /// <param name="cancellationToken">Passed to the tool's handler.</param>
    /// <returns>A result for <paramref name="call"/>, marked as an error when the handler failed.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="call"/> is <see langword="null"/>.</exception>
    /// <exception cref="ToolLoopException">No tool with the call's name is registered.</exception>
    /// <exception cref="OperationCanceledException">The handler was cancelled.</exception>
    public async Task<ToolResult> DispatchAsync(ToolCall call, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(call);
        if (!_byName.TryGetValue(call.Name, out var tool))
        {
            var known = _byName.Count == 0 ? "(none)" : string.Join(", ", _byName.Keys.OrderBy(static name => name, StringComparer.Ordinal));
            throw new ToolLoopException($"The model called an unknown tool '{call.Name}'.", hint: $"Registered tools: {known}");
        }

        Interlocked.Increment(ref _dispatched);
        try
        {
            var output = await tool.CallAsync(call.Arguments, cancellationToken).ConfigureAwait(false);
            return new ToolResult(call.Id, ToolBinding.RenderReturn(output));
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception)
        {
            return new ToolResult(call.Id, $"{exception.GetType().Name}: {exception.Message}", isError: true);
        }
    }
}
