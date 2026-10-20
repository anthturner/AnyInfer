using System.Text.Json;

internal sealed class ScriptConsumption
{
    private readonly Dictionary<string, int> _expected = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> _consumed = new(StringComparer.Ordinal);
    private readonly object _gate = new();

    internal ScriptConsumption(IEnumerable<JsonElement> scripts)
    {
        foreach (var script in scripts)
        {
            var id = script.GetProperty("id").GetString() ?? throw new FormatException("A script identifier is required.");
            if (!_expected.TryAdd(id, script.GetProperty("steps").GetArrayLength()))
            {
                throw new FormatException("Retrieval script identifiers must be unique.");
            }
        }
    }

    internal void Consumed(string id)
    {
        lock (_gate)
        {
            var next = _consumed.GetValueOrDefault(id) + 1;
            if (!_expected.TryGetValue(id, out var expected) || next > expected)
            {
                throw new InvalidOperationException("A retrieval script was consumed more than once.");
            }

            _consumed[id] = next;
        }
    }

    internal void RequireComplete()
    {
        lock (_gate)
        {
            if (_expected.Any(pair => _consumed.GetValueOrDefault(pair.Key) != pair.Value))
            {
                throw new InvalidOperationException("A retrieval script was not consumed exactly.");
            }
        }
    }
}
