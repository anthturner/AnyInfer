using System.Collections.ObjectModel;
using System.Text;
using AnyInfer.Internal;
using AnyInfer.Json;

namespace AnyInfer.Capabilities;

/// <summary>Persists caller-selected ledger snapshots in the version-one accounting format.</summary>
public sealed class SpendStore
{
    /// <summary>Gets the persisted accounting format version.</summary>
    public const int FormatVersion = 1;
    private const int MaximumBuckets = 512;

    /// <summary>Creates an inert store at a caller-selected path.</summary>
    public SpendStore(string path)
    {
        Path = path ?? throw new ArgumentNullException(nameof(path));
    }

    /// <summary>Gets the caller-selected store path.</summary>
    public string Path { get; }

    /// <summary>Loads readable version-one buckets, skipping unreadable individual bucket values.</summary>
    public IReadOnlyDictionary<string, SpendTotals> Load()
    {
        try
        {
            if (!File.Exists(Path))
            {
                return Empty;
            }

            var bytes = File.ReadAllBytes(Path);
            if (JsonReader.Read(bytes) is not JsonObject root ||
                !root.TryGetValue("format_version", out var version) ||
                version is not JsonInteger integer || integer.Value != 1 ||
                !root.TryGetValue("buckets", out var rawBuckets) || rawBuckets is not JsonObject buckets)
            {
                return Empty;
            }

            var result = new Dictionary<string, SpendTotals>(StringComparer.Ordinal);
            foreach (var bucket in buckets.Properties)
            {
                if (bucket.Value is JsonObject value && SpendTotals.FromDictionary(value) is { } totals)
                {
                    result[bucket.Name] = totals;
                }
            }

            return Snapshot(result);
        }
        catch (IOException)
        {
            return Empty;
        }
        catch (UnauthorizedAccessException)
        {
            return Empty;
        }
        catch (FormatException)
        {
            return Empty;
        }
        catch (ArgumentException)
        {
            return Empty;
        }
    }

    /// <summary>Adds a ledger snapshot to one named bucket and atomically replaces the store file.</summary>
    public void Accumulate(SpendLedger ledger, string bucket = "total")
    {
        ArgumentNullException.ThrowIfNull(ledger);
        ArgumentNullException.ThrowIfNull(bucket);
        var entries = new Dictionary<string, SpendTotals>(Load(), StringComparer.Ordinal);
        var incoming = ledger.Totals();
        if (entries.TryGetValue(bucket, out var existing))
        {
            if (!string.Equals(existing.Currency, incoming.Currency, StringComparison.Ordinal))
            {
                throw new ArgumentException($"Stored bucket '{bucket}' has a different currency.", nameof(bucket));
            }

            incoming = Add(existing, incoming);
        }

        entries[bucket] = incoming;
        while (entries.Count > MaximumBuckets)
        {
            entries.Remove(entries.Keys.First());
        }

        var buckets = new JsonObject(entries.Select(static item => new JsonProperty(item.Key, item.Value.ToDictionary())));
        var root = new JsonObject([
            new JsonProperty("format_version", new JsonInteger(FormatVersion)),
            new JsonProperty("buckets", buckets),
        ]);
        WriteAtomically(JsonWriter.WriteAccounting(root, indent: 2));
    }

    private void WriteAtomically(string contents)
    {
        var destination = System.IO.Path.GetFullPath(Path);
        var directory = System.IO.Path.GetDirectoryName(destination) ?? throw new ArgumentException("Store path has no directory.", nameof(Path));
        Directory.CreateDirectory(directory);
        var temporary = System.IO.Path.Combine(directory, $".{System.IO.Path.GetFileName(destination)}.{Guid.NewGuid():N}.tmp");
        try
        {
            var platformContents = Environment.NewLine == "\n"
                ? contents
                : contents.Replace("\n", Environment.NewLine, StringComparison.Ordinal);
            File.WriteAllText(temporary, platformContents, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            File.Move(temporary, destination, overwrite: true);
        }
        finally
        {
            try { if (File.Exists(temporary)) File.Delete(temporary); } catch (IOException) { }
        }
    }

    private static SpendTotals Add(SpendTotals left, SpendTotals right) => new(
        AccountingDecimal.Add(left.Cost, right.Cost),
        left.Currency,
        checked(left.Requests + right.Requests),
        checked(left.UnknownRequests + right.UnknownRequests),
        checked(left.InputTokens + right.InputTokens),
        checked(left.OutputTokens + right.OutputTokens),
        checked(left.CacheReadTokens + right.CacheReadTokens));

    private static readonly IReadOnlyDictionary<string, SpendTotals> Empty =
        new ReadOnlyDictionary<string, SpendTotals>(new Dictionary<string, SpendTotals>(StringComparer.Ordinal));

    private static IReadOnlyDictionary<string, SpendTotals> Snapshot(IReadOnlyDictionary<string, SpendTotals> entries) =>
        new ReadOnlyDictionary<string, SpendTotals>(new Dictionary<string, SpendTotals>(entries, StringComparer.Ordinal));
}
