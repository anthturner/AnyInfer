using System.Text;

namespace AnyInfer.Capabilities;

/// <summary>Provides dependency-free UTF-8 byte heuristic token estimates.</summary>
public sealed record HeuristicTokenEstimator : ITokenEstimator
{
    /// <summary>Initializes the estimator with a positive finite planning multiplier.</summary>
    /// <param name="multiplier">Factor applied to the planning count only; the lower bound is never inflated by it.</param>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="multiplier"/> is not a positive finite number.</exception>
    public HeuristicTokenEstimator(double multiplier = 1.0)
    {
        if (!double.IsFinite(multiplier) || multiplier <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(multiplier), "Estimator multiplier must be a positive finite number.");
        }

        Multiplier = multiplier;
    }

    /// <summary>Gets the planning-only calibration multiplier.</summary>
    public double Multiplier { get; }

    /// <summary>Estimates text from UTF-8 bytes, without inflating its lower bound.</summary>
    /// <param name="text">Text to estimate.</param>
    /// <returns>
    /// A planning count of <c>ceil(bytes / 3)</c> scaled by <see cref="Multiplier"/> and rounded up, and a floor
    /// of <c>bytes / 8</c> (integer division) never above the planning count. Both are estimates, not exact counts.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
    public TokenEstimate Estimate(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        var bytes = (long)Encoding.UTF8.GetByteCount(text);
        var baseTokens = checked((long)Math.Ceiling(bytes / (double)TokenEstimation.EstimateBytesPerToken));
        var tokens = checked((long)Math.Ceiling(baseTokens * Multiplier));
        return new TokenEstimate(tokens, Math.Min(bytes / TokenEstimation.FloorBytesPerToken, tokens));
    }
}
