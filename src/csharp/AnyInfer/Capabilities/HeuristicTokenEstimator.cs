using System.Text;

namespace AnyInfer.Capabilities;

/// <summary>Provides dependency-free UTF-8 byte heuristic token estimates.</summary>
public sealed record HeuristicTokenEstimator : ITokenEstimator
{
    /// <summary>Initializes the estimator with a positive finite planning multiplier.</summary>
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
    public TokenEstimate Estimate(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        var bytes = (long)Encoding.UTF8.GetByteCount(text);
        var baseTokens = checked((long)Math.Ceiling(bytes / (double)TokenEstimation.EstimateBytesPerToken));
        var tokens = checked((long)Math.Ceiling(baseTokens * Multiplier));
        return new TokenEstimate(tokens, Math.Min(bytes / TokenEstimation.FloorBytesPerToken, tokens));
    }
}
