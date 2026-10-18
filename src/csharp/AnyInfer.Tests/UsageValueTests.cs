using AnyInfer.Capabilities;
using AnyInfer.Internal;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Pure reported-usage and pricing value controls for the fixed native accounting domain.</summary>
public sealed class UsageValueTests
{
    [Fact]
    public void Usage_distinguishes_unknown_from_zero_and_snapshots_ordinal_server_tool_maps()
    {
        var supplied = new Dictionary<string, long>(StringComparer.Ordinal) { ["search"] = 0 };
        var unknown = new Usage();
        var knownZero = new Usage(InputTokens: 0, OutputTokens: 0, TotalTokens: 0, CostUsd: EDecimal.Zero, SearchUnits: 0, ServerToolUses: supplied);
        supplied["search"] = 99;

        Assert.Null(unknown.InputTokens);
        Assert.Equal(0, knownZero.InputTokens);
        Assert.Equal(0, knownZero.SearchUnits);
        Assert.Equal(0, knownZero.ServerToolUses["search"]);
        AssertMapImmutable(knownZero.ServerToolUses, "later", 1);
        Assert.NotEqual(unknown, knownZero);
    }

    [Fact]
    public void Usage_numeric_decimal_equality_hash_and_reported_nonfinite_values_are_preserved()
    {
        var onePointZero = new Usage(CostUsd: EDecimal.FromString("1.0"));
        var onePointZeroZero = new Usage(CostUsd: EDecimal.FromString("1.00"));
        var positiveZero = new Usage(CostUsd: EDecimal.Zero);
        var negativeZero = new Usage(CostUsd: EDecimal.FromString("-0"));
        var nan = new Usage(CostUsd: EDecimal.NaN);

        Assert.Equal(onePointZero, onePointZeroZero);
        Assert.Equal(onePointZero.GetHashCode(), onePointZeroZero.GetHashCode());
        Assert.Equal(positiveZero, negativeZero);
        Assert.Equal(positiveZero.GetHashCode(), negativeZero.GetHashCode());
        Assert.Equal(EDecimal.NaN, nan.CostUsd);
    }

    [Fact]
    public void Usage_normalize_merge_and_sum_keep_the_source_unknown_and_server_tool_boundaries()
    {
        var tools = new Dictionary<string, long>(StringComparer.Ordinal) { ["search"] = 2 };
        var initial = new Usage(InputTokens: 2, OutputTokens: 3, ServerToolUses: tools);
        var normalized = initial.Normalized();
        var merged = initial.Merge(new Usage(InputTokens: 7, SearchUnits: 1));
        var summed = Usage.Sum([new Usage(InputTokens: 2, OutputTokens: 3, CostUsd: EDecimal.FromString("1E-34"), ServerToolUses: tools), new Usage(InputTokens: 5, OutputTokens: 7, CostUsd: EDecimal.FromString("2E-34"), ServerToolUses: tools)]);

        Assert.Equal(5, normalized.TotalTokens);
        Assert.Equal(2, normalized.ServerToolUses["search"]);
        Assert.Equal(7, merged.InputTokens);
        Assert.Equal(3, merged.OutputTokens);
        Assert.Empty(merged.ServerToolUses);
        Assert.Equal(7, summed.InputTokens);
        Assert.Equal(10, summed.OutputTokens);
        Assert.Equal(EDecimal.FromString("3E-34"), summed.CostUsd);
        Assert.Empty(summed.ServerToolUses);
        Assert.Null(Usage.Sum([new Usage(InputTokens: 1), new Usage()]).InputTokens);
    }

    [Fact]
    public void Owned_accounting_uses_fixed_flag_free_trapping_context_and_exact_values_outside_arithmetic_precision()
    {
        var outsidePrecision = EDecimal.FromString("123456789012345678901234567890.123456789");
        var tinyPrice = EDecimal.FromString("1E-34");

        Assert.Equal(outsidePrecision, new Pricing(outsidePrecision, tinyPrice).InputPer1M);
        Assert.Equal(tinyPrice, AccountingDecimal.Price(tinyPrice, 1_000_000));
        Assert.Throws<ETrapException>(() => AccountingDecimal.Add(EDecimal.FromString("9.999999999999999999999999999E+999999"), EDecimal.FromString("9.999999999999999999999999999E+999999")));
        Assert.Equal(EDecimal.FromInt32(3), AccountingDecimal.Add(EDecimal.One, EDecimal.FromInt32(2)));
    }

    [Fact]
    public void Pricing_uses_exact_decimal_values_and_ordinal_snapshot_maps_with_numeric_equality()
    {
        var source = new Dictionary<string, EDecimal>(StringComparer.Ordinal) { ["web"] = EDecimal.FromString("0.010") };
        var left = new Pricing(EDecimal.FromString("1.0"), EDecimal.FromString("2.00"), perServerToolUse: source);
        var right = new Pricing(EDecimal.FromString("1.00"), EDecimal.FromString("2.0"), perServerToolUse: new Dictionary<string, EDecimal>(StringComparer.Ordinal) { ["web"] = EDecimal.FromString("0.01") });
        source["web"] = EDecimal.FromInt32(9);

        Assert.Equal(left, right);
        Assert.Equal(left.GetHashCode(), right.GetHashCode());
        Assert.Equal(0, left.PerServerToolUse["web"].CompareTo(EDecimal.FromString("0.01")));
        Assert.Equal("0.010", left.PerServerToolUse["web"].ToString());
        AssertMapImmutable(left.PerServerToolUse, "later", EDecimal.One);
    }

    private static void AssertMapImmutable<T>(IReadOnlyDictionary<string, T> snapshot, string key, T value)
    {
        if (snapshot is not IDictionary<string, T> mutable)
        {
            return;
        }

        Assert.True(mutable.IsReadOnly);
        Assert.Throws<NotSupportedException>(() => mutable.Add(key, value));
    }
}
