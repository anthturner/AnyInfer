using PeterO.Numbers;

namespace AnyInfer.Internal;

/// <summary>Provides the fixed decimal context used by owned accounting arithmetic.</summary>
internal static class AccountingDecimal
{
    private static readonly EContext Context = EContext.ForPrecisionAndRounding(28, ERounding.HalfEven)
        .WithBigExponentRange(EInteger.FromInt32(-999999), EInteger.FromInt32(999999))
        .WithExponentClamp(false)
        .WithTraps(EContext.FlagInvalid | EContext.FlagDivideByZero | EContext.FlagOverflow)
        .WithNoFlags();

    internal static EDecimal Add(EDecimal left, EDecimal right) => left.Add(right, Context);

    internal static EDecimal Subtract(EDecimal left, EDecimal right) => left.Subtract(right, Context);

    internal static EDecimal Multiply(EDecimal left, EDecimal right) => left.Multiply(right, Context);

    internal static EDecimal Divide(EDecimal left, EDecimal right) => left.Divide(right, Context);

    internal static int Compare(EDecimal left, EDecimal right) =>
        left.CompareToSignal(right, Context).CompareTo(EDecimal.Zero);

    internal static string Format(EDecimal value) => value.ToString();

    internal static EDecimal Price(EDecimal rate, long tokens) =>
        EDecimal.FromInt64(tokens).Divide(EDecimal.FromInt32(1_000_000), Context).Multiply(rate, Context);

    internal static bool IsNegativeCatalogRate(EDecimal value) =>
        value.CompareToSignal(EDecimal.Zero, Context).CompareTo(EDecimal.Zero) < 0;

    internal static bool NumericEquals(EDecimal left, EDecimal right)
    {
        if (!left.IsFinite || !right.IsFinite)
        {
            return left.Equals(right);
        }

        return left.CompareTo(right) == 0;
    }

    internal static int NumericHashCode(EDecimal value)
    {
        if (!value.IsFinite)
        {
            return value.GetHashCode();
        }

        if (value.IsZero)
        {
            return 0;
        }

        return StringComparer.Ordinal.GetHashCode(value.Reduce(null).ToString());
    }
}
