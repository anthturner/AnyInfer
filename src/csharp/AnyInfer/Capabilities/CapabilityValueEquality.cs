namespace AnyInfer.Capabilities;

internal static class CapabilityValueEquality
{
    internal static bool DictionaryEquals<TKey, TValue>(
        IReadOnlyDictionary<TKey, TValue> first,
        IReadOnlyDictionary<TKey, TValue> second)
        where TKey : notnull
    {
        if (first.Count != second.Count)
        {
            return false;
        }

        var comparer = EqualityComparer<TValue>.Default;
        foreach (var pair in first)
        {
            if (!second.TryGetValue(pair.Key, out var value) || !comparer.Equals(pair.Value, value))
            {
                return false;
            }
        }

        return true;
    }

    internal static bool SequenceEquals<T>(IReadOnlyList<T> first, IReadOnlyList<T> second) =>
        first.Count == second.Count && first.SequenceEqual(second);

    internal static bool SetEquals<T>(IReadOnlySet<T> first, IReadOnlySet<T> second) => first.SetEquals(second);

    internal static void AddDictionaryHash(ref HashCode hash, IReadOnlyDictionary<string, decimal> values)
    {
        foreach (var pair in values.OrderBy(static pair => pair.Key, StringComparer.Ordinal))
        {
            hash.Add(pair.Key, StringComparer.Ordinal);
            hash.Add(pair.Value);
        }
    }

    internal static void AddSequenceHash<T>(ref HashCode hash, IReadOnlyList<T> values)
    {
        foreach (var value in values)
        {
            hash.Add(value);
        }
    }

    internal static void AddSetHash<T>(ref HashCode hash, IReadOnlySet<T> values)
        where T : struct, Enum
    {
        foreach (var value in values.OrderBy(static value => Convert.ToInt64(value)))
        {
            hash.Add(value);
        }
    }
}
