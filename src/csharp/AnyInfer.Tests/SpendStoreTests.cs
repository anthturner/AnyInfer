using System.Text;
using AnyInfer.Capabilities;
using AnyInfer.Json;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Version-one caller-owned spend-store persistence controls.</summary>
public sealed class SpendStoreTests
{
    [Fact]
    public void Store_accumulate_writes_exact_ascii_indented_v1_bytes_without_a_trailing_newline()
    {
        var directory = CreateDirectory();
        try
        {
            var path = Path.Combine(directory, "ledger.json");
            var ledger = new SpendLedger();
            ledger.Record(new ResolvedTarget("alpha", "model"), new Usage(InputTokens: 2, OutputTokens: 3, CacheReadTokens: 4, CostUsd: EDecimal.FromString("1.00")));
            var store = new SpendStore(path);

            store.Accumulate(ledger);

            var bytes = File.ReadAllBytes(path);
            var text = Encoding.UTF8.GetString(bytes);
            Assert.False(bytes.AsSpan().StartsWith(Encoding.UTF8.GetPreamble()));
            var expected = "{\n  \"format_version\": 1,\n  \"buckets\": {\n    \"total\": {\n      \"cost\": \"1.00\",\n      \"currency\": \"USD\",\n      \"requests\": 1,\n      \"unknown_requests\": 0,\n      \"input_tokens\": 2,\n      \"output_tokens\": 3,\n      \"cache_read_tokens\": 4\n    }\n  }\n}".Replace("\n", Environment.NewLine, StringComparison.Ordinal);
            Assert.Equal(expected, text);
            Assert.False(text.EndsWith("\n", StringComparison.Ordinal));
            Assert.True(bytes.AsSpan().IndexOf(Encoding.UTF8.GetBytes(Environment.NewLine)) >= 0);
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void Store_load_skips_foreign_unreadable_and_native_type_invalid_buckets()
    {
        var directory = CreateDirectory();
        try
        {
            var path = Path.Combine(directory, "ledger.json");
            var store = new SpendStore(path);
            File.WriteAllText(path, "{\"format_version\":2,\"buckets\":{}}");
            Assert.Empty(store.Load());
            File.WriteAllText(path, "{\"format_version\":1,\"buckets\":{\"bad\":{\"cost\":\"1\",\"requests\":1.5},\"good\":{\"cost\":\"-0.00\",\"requests\":1}}}");

            var loaded = store.Load();
            var good = Assert.Single(loaded);
            Assert.Equal("good", good.Key);
            Assert.Equal("-0.00", good.Value.Cost.ToString());
            Assert.Equal(1, good.Value.Requests);
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void Store_rejects_currency_mismatch_and_preserves_oldest_insertion_order_on_update()
    {
        var directory = CreateDirectory();
        try
        {
            var path = Path.Combine(directory, "ledger.json");
            var store = new SpendStore(path);
            for (var index = 0; index < 512; index++)
            {
                var ledger = new SpendLedger();
                ledger.Record(new ResolvedTarget("alpha", "model"), new Usage(CostUsd: EDecimal.One));
                store.Accumulate(ledger, index.ToString());
            }

            var update = new SpendLedger();
            update.Record(new ResolvedTarget("alpha", "model"), new Usage(CostUsd: EDecimal.One));
            store.Accumulate(update, "0");
            store.Accumulate(update, "512");
            var loaded = store.Load();
            Assert.Equal(512, loaded.Count);
            Assert.False(loaded.ContainsKey("0"));
            Assert.True(loaded.ContainsKey("1"));
            Assert.True(loaded.ContainsKey("512"));

            var eur = new SpendLedger("EUR");
            eur.Record(new ResolvedTarget("alpha", "model"), new Usage(CostUsd: EDecimal.One));
            Assert.Throws<ArgumentException>(() => store.Accumulate(eur, "1"));
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    private static string CreateDirectory()
    {
        var directory = Path.Combine(Path.GetTempPath(), "AnyInfer-Accounting-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        return directory;
    }
}
