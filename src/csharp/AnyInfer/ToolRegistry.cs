using System.Threading;
using AnyInfer.Internal;

namespace AnyInfer;

/// <summary>Ordered caller-authorized tools available to one bounded tool loop.</summary>
public sealed class ToolRegistry
{
    private readonly Dictionary<string, Tool> _byName = new(StringComparer.Ordinal);
    private readonly IReadOnlyList<ToolSpec> _specs;
    private long _dispatched;

    /// <summary>Registers tools, replacing duplicate names in their first declaration slot.</summary>
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
