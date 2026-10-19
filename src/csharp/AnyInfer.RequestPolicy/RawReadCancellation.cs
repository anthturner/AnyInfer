using System.Runtime.ExceptionServices;

/// <summary>Observer-only validation for the declared early-stream fixture read cancellation.</summary>
internal sealed record RawReadCancellationOracle(
    Task Pending,
    CancellationToken DeclaredCallerToken,
    CancellationToken? ObservedReadToken,
    bool CancellationObserved);

/// <summary>Accepts only the causal cancellation emitted by the observer-owned fixture read.</summary>
internal static class RawReadCancellation
{
    internal static async Task ObserveAsync(RawReadCancellationOracle oracle, TimeSpan joinTimeout)
    {
        try
        {
            await oracle.Pending.WaitAsync(joinTimeout).ConfigureAwait(false);
            throw new InvalidOperationException("A declared observer cancellation completed without an operation cancellation.");
        }
        catch (OperationCanceledException exception)
        {
            if (IsAccepted(exception, oracle))
            {
                return;
            }

            ExceptionDispatchInfo.Capture(exception).Throw();
            throw;
        }
    }

    private static bool IsAccepted(OperationCanceledException exception, RawReadCancellationOracle oracle)
    {
        var observed = oracle.ObservedReadToken;
        return oracle.DeclaredCallerToken.IsCancellationRequested &&
            oracle.CancellationObserved &&
            observed.HasValue &&
            observed.Value.IsCancellationRequested &&
            (exception.CancellationToken == oracle.DeclaredCallerToken || exception.CancellationToken == observed.Value);
    }
}
