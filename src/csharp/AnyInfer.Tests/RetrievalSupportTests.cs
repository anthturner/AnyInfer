using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Immutable retrieval support DTO and failure-shape controls.</summary>
public sealed class RetrievalSupportTests
{
    [Fact]
    public void Batch_failure_retains_its_literal_four_fields_without_extra_validation()
    {
        var defaultError = new BatchFailure(-1, 0, succeeded: false);
        var unusualValues = new BatchFailure(int.MinValue, -7, succeeded: true, error: string.Empty);

        Assert.Equal(-1, defaultError.BatchIndex);
        Assert.Equal(0, defaultError.ItemCount);
        Assert.False(defaultError.Succeeded);
        Assert.Null(defaultError.Error);
        Assert.Equal(int.MinValue, unusualValues.BatchIndex);
        Assert.Equal(-7, unusualValues.ItemCount);
        Assert.True(unusualValues.Succeeded);
        Assert.Equal(string.Empty, unusualValues.Error);
    }

    [Fact]
    public void Attempt_record_appends_optional_timing_without_changing_legacy_constructor_positions()
    {
        var target = new ResolvedTarget("fixture", "model");
        var error = new ProviderUnavailableException("unavailable");
        var timing = new Timing(1, totalMs: 2);

        var legacy = new AttemptRecord(target, "failed", error);
        var measured = new AttemptRecord(target, "ok", timing: timing);

        Assert.Same(target, legacy.Target);
        Assert.Equal("failed", legacy.Outcome);
        Assert.Same(error, legacy.Error);
        Assert.Null(legacy.Timing);
        Assert.Same(target, measured.Target);
        Assert.Equal("ok", measured.Outcome);
        Assert.Null(measured.Error);
        Assert.Same(timing, measured.Timing);
    }

    [Fact]
    public void All_targets_failed_appends_copied_batch_failures_after_native_inner_and_preserves_existing_error_shape()
    {
        var attempt = new AttemptRecord(new ResolvedTarget("fixture", "model"), "failed");
        var failures = new List<BatchFailure>
        {
            new(0, 2, succeeded: true),
            new(1, 1, succeeded: false, error: "bounded detail"),
        };
        var nativeInner = new InvalidOperationException("native sentinel");

        var error = new AllTargetsFailedException(
            "exhausted",
            [attempt],
            provider: "fixture",
            detail: "detail",
            hint: "hint",
            nativeInner: nativeInner,
            batchFailures: failures);
        failures.Clear();

        Assert.Equal("all_targets_failed", error.Category);
        Assert.Equal("generate", error.Phase);
        Assert.Equal("fixture", error.Provider);
        Assert.Equal("detail", error.Detail);
        Assert.Equal("hint", error.Hint);
        Assert.Same(nativeInner, error.NativeInner);
        Assert.Same(attempt, Assert.Single(error.Attempts));
        Assert.Collection(
            error.BatchFailures,
            first =>
            {
                Assert.Equal(0, first.BatchIndex);
                Assert.True(first.Succeeded);
            },
            second =>
            {
                Assert.Equal(1, second.BatchIndex);
                Assert.False(second.Succeeded);
                Assert.Equal("bounded detail", second.Error);
            });

        if (error.BatchFailures is IList<BatchFailure> mutable)
        {
            Assert.Throws<NotSupportedException>(() => mutable.Add(new BatchFailure(2, 1, false)));
        }
    }

    [Fact]
    public void All_targets_failed_defaults_to_an_empty_read_only_batch_failure_snapshot()
    {
        var error = new AllTargetsFailedException("exhausted", [new AttemptRecord(null, "failed")]);

        Assert.Empty(error.BatchFailures);
        if (error.BatchFailures is IList<BatchFailure> mutable)
        {
            Assert.Throws<NotSupportedException>(() => mutable.Add(new BatchFailure(0, 1, false)));
        }
    }
}
