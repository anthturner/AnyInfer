using AnyInfer.Json;

namespace AnyInfer.Internal;

/// <summary>Creates ordinal, read-only snapshots for public immutable value records.</summary>
internal static class ImmutableValues
{
    internal static IReadOnlyList<T> List<T>(IEnumerable<T>? values, string parameterName)
    {
        return new SnapshotList<T>(values, parameterName);
    }

    internal static IReadOnlyDictionary<string, T> Map<T>(IEnumerable<KeyValuePair<string, T>>? values, string parameterName)
    {
        return new SnapshotMap<T>(values, parameterName);
    }

    internal static bool MapEquals<T>(IReadOnlyDictionary<string, T> left, IReadOnlyDictionary<string, T> right)
    {
        return left.Count == right.Count && left.All(pair => right.TryGetValue(pair.Key, out var other) && EqualsValue(pair.Value, other));
    }

    internal static void AddMapHash<T>(ref HashCode hash, IReadOnlyDictionary<string, T> values)
    {
        foreach (var pair in values.OrderBy(static pair => pair.Key, StringComparer.Ordinal))
        {
            hash.Add(pair.Key, StringComparer.Ordinal);
            AddValueHash(ref hash, pair.Value);
        }
    }

    internal static bool EqualsValue<T>(T left, T right)
    {
        return left is JsonValue leftJson && right is JsonValue rightJson
            ? JsonEquality.TypeAwareEquals(leftJson, rightJson)
            : EqualityComparer<T>.Default.Equals(left, right);
    }

    internal static void AddValueHash<T>(ref HashCode hash, T value)
    {
        if (value is JsonValue json)
        {
            AddJsonHash(ref hash, json);
            return;
        }
        hash.Add(value);
    }

    internal static void AddJsonHash(ref HashCode hash, JsonValue value)
    {
        hash.Add(value.GetType());
        switch (value)
        {
            case JsonNull:
                return;
            case JsonBoolean boolean:
                hash.Add(boolean.Value);
                return;
            case JsonInteger integer:
                hash.Add(integer.Value);
                return;
            case JsonNumber number:
                hash.Add(BitConverter.DoubleToInt64Bits(number.Value));
                return;
            case JsonString text:
                hash.Add(text.Value, StringComparer.Ordinal);
                return;
            case JsonArray array:
                foreach (var item in array.Items)
                {
                    AddJsonHash(ref hash, item);
                }

                return;
            case JsonObject obj:
                foreach (var property in obj.Properties.OrderBy(static property => property.Name, StringComparer.Ordinal))
                {
                    hash.Add(property.Name, StringComparer.Ordinal);
                    AddJsonHash(ref hash, property.Value);
                }

                return;
            default: throw new ArgumentOutOfRangeException(nameof(value));
        }
    }
}

internal sealed class SnapshotList<T> : IReadOnlyList<T>, IEquatable<SnapshotList<T>>
{
    private readonly T[] _items;
    internal SnapshotList(IEnumerable<T>? values, string parameterName)
    {
        _items = (values ?? [])
            .Select(value => value is null
                ? throw new ArgumentException("Collections cannot contain null elements.", parameterName)
                : value)
            .ToArray();
    }
    public int Count => _items.Length;
    public T this[int index] => _items[index];
    public IEnumerator<T> GetEnumerator() => ((IEnumerable<T>)_items).GetEnumerator();
    System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => _items.GetEnumerator();
    public bool Equals(SnapshotList<T>? other)
    {
        return other is not null
            && _items.Length == other._items.Length
            && _items.Zip(other._items).All(static pair => ImmutableValues.EqualsValue(pair.First, pair.Second));
    }
    public override bool Equals(object? obj) => obj is SnapshotList<T> other && Equals(other);
    public override int GetHashCode()
    {
        var hash = new HashCode();
        foreach (var item in _items)
        {
            ImmutableValues.AddValueHash(ref hash, item);
        }

        return hash.ToHashCode();
    }
}

internal sealed class SnapshotMap<T> : IReadOnlyDictionary<string, T>, IEquatable<SnapshotMap<T>>
{
    private readonly Dictionary<string, T> _values;
    internal SnapshotMap(IEnumerable<KeyValuePair<string, T>>? values, string parameterName)
    {
        _values = new Dictionary<string, T>(StringComparer.Ordinal);
        foreach (var pair in values ?? [])
        {
            if (pair.Key is null || pair.Value is null)
            {
                throw new ArgumentException("Maps cannot contain null keys or values.", parameterName);
            }
            _values[pair.Key] = pair.Value;
        }
    }
    public int Count => _values.Count;
    public IEnumerable<string> Keys => _values.Keys;
    public IEnumerable<T> Values => _values.Values;
    public T this[string key] => _values[key];
    public bool ContainsKey(string key) => _values.ContainsKey(key);
    public bool TryGetValue(string key, out T value) => _values.TryGetValue(key, out value!);
    public IEnumerator<KeyValuePair<string, T>> GetEnumerator() => _values.GetEnumerator();
    System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    public bool Equals(SnapshotMap<T>? other) => other is not null && ImmutableValues.MapEquals(this, other);
    public override bool Equals(object? obj) => obj is SnapshotMap<T> other && Equals(other);
    public override int GetHashCode()
    {
        var hash = new HashCode();
        ImmutableValues.AddMapHash(ref hash, this);
        return hash.ToHashCode();
    }
}
