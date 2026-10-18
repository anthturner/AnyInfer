using System.Numerics;
using AnyInfer.Internal;
using AnyInfer.Json;
using PeterO.Numbers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Accounting JSON and reported-usage numeric-boundary controls.</summary>
public sealed class AccountingValueTests
{
    [Fact]
    public void Accounting_writer_preserves_insertion_order_python_spacing_ascii_and_arbitrary_integers()
    {
        var large = BigInteger.Parse("100000000000000000000000000000000000000000000000000000000000000000000000000");
        var value = new JsonObject([
            new JsonProperty("z", new JsonString("é😀")),
            new JsonProperty("a", new JsonArray([new JsonInteger(large), new JsonNumber(-0d, "-0"), new JsonNumber(1e20, "ignored")])),
        ]);

        Assert.Equal("{\"z\": \"\\u00e9\\ud83d\\ude00\", \"a\": [100000000000000000000000000000000000000000000000000000000000000000000000000, -0.0, 1e+20]}", JsonWriter.WriteAccounting(value));
        Assert.Equal(
            "{\n  \"z\": \"\\u00e9\\ud83d\\ude00\",\n  \"a\": [\n    100000000000000000000000000000000000000000000000000000000000000000000000000,\n    -0.0,\n    1e+20\n  ]\n}",
            JsonWriter.WriteAccounting(value, indent: 2));
        Assert.False(JsonWriter.WriteAccounting(value, indent: 2).EndsWith("\n", StringComparison.Ordinal));

        Assert.Equal("{\"a\":[100000000000000000000000000000000000000000000000000000000000000000000000000,-0.0,1e+20],\"z\":\"\\u00e9\\ud83d\\ude00\"}", JsonWriter.WriteManifestCanonical(value));
    }

    [Fact]
    public void Existing_writer_modes_remain_distinct_from_accounting_policy()
    {
        var value = new JsonObject([
            new JsonProperty("z", new JsonString("é")),
            new JsonProperty("a", new JsonInteger(2)),
        ]);

        Assert.Equal("{\"z\": \"\\u00e9\", \"a\": 2}", JsonWriter.WriteAccounting(value));
        Assert.Equal("{\"z\":\"é\",\"a\":2}", JsonWriter.Write(value));
        Assert.Equal("{\n  \"a\": 2,\n  \"z\": \"\\u00e9\"\n}", JsonWriter.WriteCanonical(value));
    }

    [Fact]
    public void Usage_normalized_checks_only_the_derived_total_and_preserves_reported_fields()
    {
        var cost = PeterO.Numbers.EDecimal.FromString("1.25");
        var tools = new Dictionary<string, long>(StringComparer.Ordinal) { ["search"] = 2 };

        Assert.Throws<OverflowException>(() => new Usage(InputTokens: long.MaxValue, OutputTokens: 1).Normalized());
        Assert.Throws<OverflowException>(() => new Usage(InputTokens: long.MinValue, OutputTokens: -1).Normalized());

        var upperBoundary = new Usage(InputTokens: long.MaxValue - 1, OutputTokens: 1, CostUsd: cost, ServerToolUses: tools).Normalized();
        Assert.Equal(long.MaxValue, upperBoundary.TotalTokens);
        Assert.Same(cost, upperBoundary.CostUsd);
        Assert.Equal(2, upperBoundary.ServerToolUses["search"]);

        var explicitTotal = new Usage(InputTokens: long.MaxValue, OutputTokens: 1, TotalTokens: 7, CostUsd: cost, ServerToolUses: tools).Normalized();
        Assert.Same(explicitTotal, explicitTotal.Normalized());
        Assert.Equal(7, explicitTotal.TotalTokens);
        Assert.Same(cost, explicitTotal.CostUsd);
        Assert.Equal(2, explicitTotal.ServerToolUses["search"]);

        var unknown = new Usage(InputTokens: 9, CostUsd: cost, ServerToolUses: tools);
        Assert.Same(unknown, unknown.Normalized());
        Assert.Null(unknown.TotalTokens);
        Assert.Same(cost, unknown.CostUsd);
        Assert.Equal(2, unknown.ServerToolUses["search"]);
    }

    [Fact]
    public void Accounting_decimal_uses_fixed_ordered_trapping_math_without_poisoning_later_operations()
    {
        Assert.Equal(0, AccountingDecimal.Add(EDecimal.FromString("0.40"), EDecimal.FromString("0.60")).CompareTo(EDecimal.One));
        Assert.Equal(0, AccountingDecimal.Multiply(EDecimal.FromString("0.2"), EDecimal.FromString("0.3")).CompareTo(EDecimal.FromString("0.06")));
        Assert.Equal(0, AccountingDecimal.Divide(EDecimal.One, EDecimal.FromInt32(8)).CompareTo(EDecimal.FromString("0.125")));
        Assert.Throws<ETrapException>(() => AccountingDecimal.Divide(EDecimal.One, EDecimal.Zero));
        Assert.Equal(1, AccountingDecimal.Compare(EDecimal.FromInt32(3), EDecimal.Zero));
        Assert.Equal("-0.00", AccountingDecimal.Format(EDecimal.FromString("-0.00")));
        Assert.Equal(0, AccountingDecimal.Add(EDecimal.One, EDecimal.FromInt32(2)).CompareTo(EDecimal.FromInt32(3)));
    }

    [Fact]
    public void Spend_policy_limit_error_and_totals_use_numeric_money_value_semantics()
    {
        var left = new AnyInfer.Capabilities.SpendTotals(EDecimal.FromString("1.0"), requests: 1);
        var right = new AnyInfer.Capabilities.SpendTotals(EDecimal.FromString("1.00"), requests: 1);
        Assert.Equal(left, right);
        Assert.Equal(left.GetHashCode(), right.GetHashCode());
        Assert.True(new SpendPolicy(EDecimal.One, onUnknown: "refuse").Active);
        Assert.False(new SpendPolicy().Active);
        Assert.Throws<ArgumentOutOfRangeException>(() => new SpendPolicy(EDecimal.FromString("-1")));
        Assert.Throws<ArgumentException>(() => new SpendPolicy(onUnknown: "other"));

        var error = new SpendLimitException("limit", EDecimal.FromInt32(3), EDecimal.One, EDecimal.FromInt32(2), "reduce");
        Assert.Equal("spend_limit", error.Category);
        Assert.Equal("generate", error.Phase);
        Assert.False(error.Retryable);
        Assert.Equal("2", error.EstimatedUsd!.ToString());
    }
}
