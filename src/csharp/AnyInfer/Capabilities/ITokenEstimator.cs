namespace AnyInfer.Capabilities;

/// <summary>Counts text as a conservative planning estimate and lower bound.</summary>
public interface ITokenEstimator
{
    /// <summary>Estimates the supplied text without sending it to a provider.</summary>
    /// <remarks>
    /// The call is synchronous, and a client configured with this estimator makes it before dispatch while
    /// sizing, gating, or planning a request. SDK helpers throw <see cref="InvalidOperationException"/> when an
    /// implementation returns <see langword="null"/>.
    /// </remarks>
    /// <param name="text">Text to estimate.</param>
    /// <returns>
    /// A high-biased planning count and a low-biased lower bound. An exact counter returns equal values.
    /// </returns>
    TokenEstimate Estimate(string text);
}
