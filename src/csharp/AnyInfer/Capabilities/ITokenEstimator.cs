namespace AnyInfer.Capabilities;

/// <summary>Counts text as a conservative planning estimate and lower bound.</summary>
public interface ITokenEstimator
{
    /// <summary>Estimates the supplied text without sending it to a provider.</summary>
    TokenEstimate Estimate(string text);
}
