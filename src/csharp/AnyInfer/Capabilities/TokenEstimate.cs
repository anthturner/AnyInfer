namespace AnyInfer.Capabilities;

/// <summary>Represents a conservative token estimate and an independent lower bound.</summary>
public sealed record TokenEstimate
{
    /// <summary>Initializes one token estimate without imposing a synthetic nonnegative domain.</summary>
    /// <param name="tokens">High-biased planning count, used to decide how much more material fits.</param>
    /// <param name="floor">Low-biased lower bound, the only figure the pre-dispatch gate refuses on.</param>
    public TokenEstimate(long tokens, long floor)
    {
        Tokens = tokens;
        Floor = floor;
    }

    /// <summary>Gets the conservative planning count.</summary>
    public long Tokens { get; }

    /// <summary>Gets the defensible lower-bound count.</summary>
    public long Floor { get; }

    /// <summary>Adds planning and lower-bound counts with native checked range semantics.</summary>
    /// <param name="other">Estimate to add.</param>
    /// <returns>A new estimate whose planning count and floor are the componentwise sums.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="other"/> is <see langword="null"/>.</exception>
    /// <exception cref="OverflowException">A sum exceeds the range of <see cref="long"/>.</exception>
    public TokenEstimate Add(TokenEstimate other)
    {
        ArgumentNullException.ThrowIfNull(other);
        return new TokenEstimate(checked(Tokens + other.Tokens), checked(Floor + other.Floor));
    }

    /// <summary>Adds two estimates componentwise with native checked range semantics.</summary>
    /// <param name="left">First estimate.</param>
    /// <param name="right">Second estimate.</param>
    /// <returns>A new estimate whose planning count and floor are the componentwise sums.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="left"/> or <paramref name="right"/> is <see langword="null"/>.</exception>
    /// <exception cref="OverflowException">A sum exceeds the range of <see cref="long"/>.</exception>
    public static TokenEstimate operator +(TokenEstimate left, TokenEstimate right)
    {
        ArgumentNullException.ThrowIfNull(left);
        return left.Add(right);
    }
}
