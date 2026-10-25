using AnyInfer.Internal;
using PeterO.Numbers;

namespace AnyInfer.Capabilities;

/// <summary>Represents a preflight lower and upper cost range without conflating it with reported spend.</summary>
public sealed record CostEstimate
{
    /// <summary>Initializes an exact preflight cost range.</summary>
    /// <param name="low">Estimated minimum cost under the estimate's assumptions.</param>
    /// <param name="high">Estimated maximum cost under the estimate's assumptions.</param>
    /// <param name="currency">Currency code of both amounts.</param>
    /// <exception cref="ArgumentNullException">An argument is <see langword="null"/>.</exception>
    public CostEstimate(EDecimal low, EDecimal high, string currency = "USD")
    {
        Low = low ?? throw new ArgumentNullException(nameof(low));
        High = high ?? throw new ArgumentNullException(nameof(high));
        Currency = currency ?? throw new ArgumentNullException(nameof(currency));
    }

    /// <summary>Gets the estimated minimum cost.</summary>
    public EDecimal Low { get; }

    /// <summary>Gets the estimated maximum cost.</summary>
    public EDecimal High { get; }

    /// <summary>Gets the quoted currency.</summary>
    public string Currency { get; }

    /// <inheritdoc />
    public bool Equals(CostEstimate? other) => other is not null
        && AccountingDecimal.NumericEquals(Low, other.Low)
        && AccountingDecimal.NumericEquals(High, other.High)
        && string.Equals(Currency, other.Currency, StringComparison.Ordinal);

    /// <inheritdoc />
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(AccountingDecimal.NumericHashCode(Low));
        hash.Add(AccountingDecimal.NumericHashCode(High));
        hash.Add(Currency, StringComparer.Ordinal);
        return hash.ToHashCode();
    }
}
