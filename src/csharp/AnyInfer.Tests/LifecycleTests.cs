using System.Runtime.CompilerServices;
using AnyInfer;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;
using Xunit;

namespace AnyInfer.Tests;

public sealed class LifecycleTests
{
    [Fact]
    public async Task Invocation_is_lazy_even_when_a_never_started_enumerator_is_disposed()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterFinal("stop")));
        var stream = AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original);

        await using (var enumerator = stream.GetAsyncEnumerator())
        {
            // Obtaining and closing the outer enumerator must not create an entry or CTS.
        }

        Assert.Empty(adapter.GenerateTokens);
        Assert.Empty(capture.Entries);
        Assert.Empty(capture.Lifecycle);
        Assert.Null(operation.LastEntry);
        Assert.Equal(0, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Invocation_passes_one_linked_token_to_adapter_and_enumerator_and_forwards_same_events()
    {
        var first = new AdapterTextDelta("one");
        var second = new AdapterFinal("stop");
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var request = Request(timeoutS: 7.25, maxResponseBytes: 73);
        var adapter = new TestAdapter((_, token) => YieldAsync(token, first, second));

        var observed = await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, request, operation, EntryRole.Original));

        Assert.Equal(2, observed.Count);
        Assert.Same(first, observed[0]);
        Assert.Same(second, observed[1]);
        Assert.Single(adapter.GenerateTokens);
        Assert.Single(adapter.EnumeratorTokens);
        Assert.Equal(adapter.GenerateTokens[0], adapter.EnumeratorTokens[0]);
        var entry = Assert.Single(capture.Entries);
        Assert.Same(request, entry.Request);
        Assert.Equal(7.25, entry.Timeout.EffectiveTimeoutS);
        Assert.Equal(73, entry.Request.MaxResponseBytes);
        Assert.Equal(observed, entry.AdapterEvents);
        Assert.Equal(0, adapter.DisposeCalls);
        AssertLifecycle(entry, capture, "created", "configured", "entered", "cleanup_start", "cleanup_end", "exited", "disposed");
    }

    [Fact]
    public async Task Default_timeout_and_actual_wire_byte_cap_are_retained_at_entry()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var request = Request(maxResponseBytes: 19);
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterFinal("stop")));

        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, request, operation, EntryRole.Original));

        var entry = Assert.Single(capture.Entries);
        Assert.Equal(120, entry.Timeout.EffectiveTimeoutS);
        Assert.Equal(19, entry.Request.MaxResponseBytes);
    }

    [Fact]
    public async Task Blocked_move_next_expires_real_scope_and_maps_to_transport_with_native_cause()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => BlockUntilCancelledAsync(token));

        var failure = await Assert.ThrowsAsync<ProviderException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 0.03), operation, EntryRole.Original)));

        Assert.Equal("transport", failure.Category);
        Assert.True(failure.Retryable);
        Assert.Equal("generate", failure.Phase);
        var entry = Assert.Single(capture.Entries);
        Assert.True(entry.Timeout.IsExpired);
        Assert.True(entry.Timeout.IsDisposed);
        Assert.IsAssignableFrom<OperationCanceledException>(entry.NativeFailure);
        Assert.Same(failure, entry.TerminalFailure);
        AssertLifecycle(entry, capture, "created", "configured", "entered", "expired", "cleanup_start", "cleanup_end", "exited", "disposed");
        Assert.Throws<ObjectDisposedException>(() => entry.Timeout.TimeoutSource.Cancel());
        Assert.Throws<ObjectDisposedException>(() => entry.Timeout.LinkedSource.Cancel());
    }

    [Fact]
    public async Task Blocked_cleanup_after_final_expires_inside_the_same_entry_scope()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => FinalThenBlockedCleanupAsync(token));
        var stream = AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 0.03), operation, EntryRole.Original);

        var outer = stream.GetAsyncEnumerator();
        Assert.True(await outer.MoveNextAsync());
        Assert.IsType<AdapterFinal>(outer.Current);
        var failure = await Assert.ThrowsAsync<ProviderException>(async () => await outer.DisposeAsync());

        Assert.Equal("transport", failure.Category);
        var entry = Assert.Single(capture.Entries);
        Assert.True(entry.Timeout.IsExpired);
        Assert.IsAssignableFrom<OperationCanceledException>(entry.NativeFailure);
        Assert.Same(failure, entry.TerminalFailure);
        Assert.Equal(0, adapter.DisposeCalls);
        AssertLifecycleTail(entry, capture, "cleanup_start", "expired", "cleanup_end", "exited", "disposed");
    }

    [Fact]
    public async Task Caller_cancellation_propagates_its_actual_cancellation_and_never_becomes_transport()
    {
        using var caller = new CancellationTokenSource();
        caller.Cancel();
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => BlockUntilCancelledAsync(token));

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 10), operation, EntryRole.Original, cancellationToken: caller.Token)));

        Assert.IsNotType<ProviderException>(failure);
        var entry = Assert.Single(capture.Entries);
        Assert.Same(failure, entry.NativeFailure);
        Assert.Same(failure, entry.TerminalFailure);
        Assert.False(entry.Timeout.IsExpired);
        Assert.DoesNotContain(capture.Lifecycle, item => item.Name == "expired");
    }

    [Fact]
    public async Task Ordinary_and_cleanup_failures_remain_the_original_exception_and_same_entry()
    {
        var ordinary = new InvalidOperationException("ordinary adapter failure");
        var ordinaryOperation = new OperationContext(new OperationCapture());
        var ordinaryAdapter = new TestAdapter((_, _) => ThrowAsync(ordinary));
        var observedOrdinary = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(ordinaryAdapter, Request(), ordinaryOperation, EntryRole.Original)));
        Assert.Same(ordinary, observedOrdinary);
        Assert.Same(ordinary, ordinaryOperation.LastEntry!.NativeFailure);
        Assert.Same(ordinary, ordinaryOperation.LastEntry.TerminalFailure);

        var fatal = new OutOfMemoryException("fatal-like adapter failure");
        var fatalOperation = new OperationContext();
        var fatalAdapter = new TestAdapter((_, _) => ThrowAsync(fatal));
        var observedFatal = await Assert.ThrowsAsync<OutOfMemoryException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(fatalAdapter, Request(), fatalOperation, EntryRole.Original)));
        Assert.Same(fatal, observedFatal);
        Assert.Same(fatal, fatalOperation.LastEntry!.NativeFailure);
        Assert.Same(fatal, fatalOperation.LastEntry!.TerminalFailure);

        var cleanup = new InvalidOperationException("cleanup failure");
        var cleanupCapture = new OperationCapture();
        var cleanupOperation = new OperationContext(cleanupCapture);
        var cleanupAdapter = new TestAdapter((_, token) => FinalThenCleanupFailureAsync(token, cleanup));
        var stream = AdapterInvocationBoundary.InvokeAsync(cleanupAdapter, Request(), cleanupOperation, EntryRole.Original);
        await using var enumerator = stream.GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        var observedCleanup = await Assert.ThrowsAsync<InvalidOperationException>(async () => await enumerator.DisposeAsync());
        Assert.Same(cleanup, observedCleanup);
        Assert.Same(cleanup, cleanupOperation.LastEntry!.NativeFailure);
        Assert.Same(cleanup, cleanupOperation.LastEntry.TerminalFailure);
        Assert.Single(cleanupCapture.Entries);
    }

    [Fact]
    public async Task Early_outer_close_cleans_the_inner_enumerator_once_without_disposing_adapter()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterTextDelta("first"), new AdapterFinal("stop")));
        var stream = AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original);

        var enumerator = stream.GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        await enumerator.DisposeAsync();
        await enumerator.DisposeAsync();

        var entry = Assert.Single(capture.Entries);
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_start"));
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_end"));
        Assert.Equal(0, adapter.DisposeCalls);
        Assert.True(entry.Timeout.IsDisposed);
    }

    [Fact]
    public async Task Original_correction_restarted_original_correction_flow_uses_four_fresh_scopes_and_latest_assessment_reference()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterFinal("stop")));
        var firstRequest = Request(timeoutS: 7.25);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, firstRequest, operation, EntryRole.Original));
        var first = operation.LastEntry!;
        Assert.True(first.Timeout.IsDisposed);

        var assessment = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"age\"]}"), JsonReader.Read("{}"), operation.OperationId, first.Ordinal);
        operation.RecordAssessment(assessment);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 7.25), operation, EntryRole.Correction, assessment));
        var correction = operation.LastEntry!;
        Assert.True(correction.Timeout.IsDisposed);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 7.25), operation, EntryRole.Original));
        var restarted = operation.LastEntry!;
        Assert.True(restarted.Timeout.IsDisposed);
        var latestAssessment = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"name\"]}"), JsonReader.Read("{}"), operation.OperationId, restarted.Ordinal);
        operation.RecordAssessment(latestAssessment);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(timeoutS: 7.25), operation, EntryRole.Correction, latestAssessment));
        var finalCorrection = operation.LastEntry!;

        Assert.Equal(new[] { 1, 2, 3, 4 }, capture.Entries.Select(entry => entry.Ordinal));
        Assert.Equal(new[] { EntryRole.Original, EntryRole.Correction, EntryRole.Original, EntryRole.Correction }, capture.Entries.Select(entry => entry.Role));
        Assert.True(first.Timeout.IsDisposed);
        Assert.True(correction.Timeout.IsDisposed);
        Assert.True(restarted.Timeout.IsDisposed);
        Assert.True(finalCorrection.Timeout.IsDisposed);
        var entries = capture.Entries.ToArray();
        Assert.Equal(4, entries.Select(entry => entry.Timeout.ContextId).Distinct().Count());
        Assert.Equal(4, entries.Select(entry => entry.Timeout.TimeoutSource).Distinct(ReferenceEqualityComparer.Instance).Count());
        Assert.Equal(4, entries.Select(entry => entry.Timeout.LinkedSource).Distinct(ReferenceEqualityComparer.Instance).Count());
        Assert.Same(assessment, correction.RepairAssessment);
        Assert.Same(latestAssessment, finalCorrection.RepairAssessment);
        Assert.Same(latestAssessment, operation.LastAssessment);
        Assert.Equal(2, capture.Assessments.Count);
        Assert.Same(assessment, capture.Assessments[0]);
        Assert.Same(latestAssessment, capture.Assessments[1]);
    }

    [Fact]
    public async Task Concurrent_operations_are_capture_isolated_and_completion_is_idempotent_without_ambient_state()
    {
        var leftCapture = new OperationCapture();
        var rightCapture = new OperationCapture();
        var left = new OperationContext(leftCapture);
        var right = new OperationContext(rightCapture);
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterTextDelta("data"), new AdapterFinal("stop")));

        await Task.WhenAll(
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request("left"), left, EntryRole.Original)),
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request("right"), right, EntryRole.Original)));
        left.Complete();
        left.Complete();
        right.Complete();
        right.Complete();

        Assert.True(left.IsClosed);
        Assert.True(right.IsClosed);
        Assert.NotEqual(left.OperationId, right.OperationId);
        Assert.Equal(left.OperationId, Assert.Single(leftCapture.Entries).OperationId);
        Assert.Equal(right.OperationId, Assert.Single(rightCapture.Entries).OperationId);
        Assert.All(leftCapture.Entries, entry => Assert.NotEqual(right.OperationId, entry.OperationId));
        Assert.All(rightCapture.Entries, entry => Assert.NotEqual(left.OperationId, entry.OperationId));
        Assert.Throws<InvalidOperationException>(() =>
            AdapterInvocationBoundary.InvokeAsync(adapter, Request(), left, EntryRole.Original).GetAsyncEnumerator().MoveNextAsync().AsTask().GetAwaiter().GetResult());
    }

    [Fact]
    public async Task Complete_rejects_new_entries_and_assessments_without_mutating_latest_or_capture()
    {
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterFinal("stop")));
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original));
        var entry = operation.LastEntry!;
        var assessment = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"age\"]}"), JsonReader.Read("{}"), operation.OperationId, entry.Ordinal);
        operation.Complete();
        operation.Complete();

        Assert.Throws<InvalidOperationException>(() => operation.RecordAssessment(assessment));
        Assert.Null(operation.LastAssessment);
        Assert.Empty(capture.Assessments);
        Assert.Same(entry, operation.LastEntry);
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original)));
        Assert.Single(capture.Entries);
    }

    [Fact]
    public async Task Correction_requires_the_latest_actual_recorded_assessment_by_reference_and_rejects_wrong_role_or_stale_values()
    {
        var operation = new OperationContext();
        var adapter = new TestAdapter(static (_, token) => YieldAsync(token, new AdapterFinal("stop")));
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original));
        var firstEntry = operation.LastEntry!;
        var firstAssessment = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"age\"]}"), JsonReader.Read("{}"), operation.OperationId, firstEntry.Ordinal);
        var equalProjection = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"age\"]}"), JsonReader.Read("{}"), operation.OperationId, firstEntry.Ordinal);

        var missing = await Assert.ThrowsAsync<ArgumentNullException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Correction)));
        Assert.Equal("repairAssessment", missing.ParamName);
        var originalWithRepair = await Assert.ThrowsAsync<ArgumentException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original, firstAssessment)));
        Assert.Equal("repairAssessment", originalWithRepair.ParamName);
        var unrecorded = await Assert.ThrowsAsync<ArgumentException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Correction, equalProjection)));
        Assert.Equal("repairAssessment", unrecorded.ParamName);

        operation.RecordAssessment(firstAssessment);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Correction, firstAssessment));
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original));
        var thirdEntry = operation.LastEntry!;
        var latestAssessment = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"name\"]}"), JsonReader.Read("{}"), operation.OperationId, thirdEntry.Ordinal);
        var foreignOperation = new OperationContext();
        var foreignAssessment = FrozenSchemaValidator.Assess(JsonReader.Read("{\"required\":[\"name\"]}"), JsonReader.Read("{}"), foreignOperation.OperationId, 1);

        var oldSourceRecord = Assert.Throws<ArgumentException>(() => operation.RecordAssessment(firstAssessment));
        Assert.Equal("assessment", oldSourceRecord.ParamName);

        var stale = await Assert.ThrowsAsync<ArgumentException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Correction, firstAssessment)));
        Assert.Equal("repairAssessment", stale.ParamName);
        var foreign = await Assert.ThrowsAsync<ArgumentException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Correction, foreignAssessment)));
        Assert.Equal("repairAssessment", foreign.ParamName);
        operation.RecordAssessment(latestAssessment);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Correction, latestAssessment));
        Assert.Same(latestAssessment, operation.LastEntry!.RepairAssessment);
    }

    [Fact]
    public async Task Move_failure_then_cleanup_failure_preserves_both_native_pairs_and_propagates_cleanup_failure()
    {
        var moveFailure = new InvalidOperationException("move failure");
        var cleanupFailure = new ApplicationException("cleanup failure");
        var capture = new OperationCapture();
        var operation = new OperationContext(capture);
        var adapter = new TestAdapter((_, _) => new DualFailureEnumerable(moveFailure, cleanupFailure));

        var observed = await Assert.ThrowsAsync<ApplicationException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original)));

        Assert.Same(cleanupFailure, observed);
        var entry = Assert.Single(capture.Entries);
        Assert.Same(cleanupFailure, entry.NativeFailure);
        Assert.Same(cleanupFailure, entry.TerminalFailure);
        Assert.Same(moveFailure, entry.PriorNativeFailure);
        Assert.Same(moveFailure, entry.PriorTerminalFailure);
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_start"));
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_end"));
        Assert.True(entry.Timeout.IsDisposed);
        Assert.Throws<ObjectDisposedException>(() => entry.Timeout.TimeoutSource.Cancel());
        Assert.Equal(0, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Capture_absence_overflow_and_reuse_do_not_change_native_delivery_or_mix_operation_evidence()
    {
        var events = new AdapterEvent[]
        {
            new AdapterTextDelta("one"), new AdapterTextDelta("two"), new AdapterTextDelta("three"), new AdapterFinal("stop"),
        };
        var uncapturedOperation = new OperationContext();
        var adapter = new TestAdapter((_, token) => YieldAsync(token, events));
        var uncapturedDelivery = await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), uncapturedOperation, EntryRole.Original));
        Assert.Equal(events, uncapturedDelivery);
        Assert.Empty(uncapturedOperation.LastEntry!.AdapterEvents);

        const int capacity = 5;
        var overflow = new OperationCapture(capacity);
        var operation = new OperationContext(overflow);
        var overflowDelivery = await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request(), operation, EntryRole.Original));
        Assert.Equal(events, overflowDelivery);
        Assert.False(overflow.IsAvailable);
        Assert.Contains("capture capacity exhausted", overflow.UnavailableReasons);
        Assert.InRange(operation.LastEntry!.AdapterEvents.Count, 0, capacity);
        Assert.True(operation.LastEntry.AdapterEvents.Count < events.Length);

        var failedCapture = new OperationCapture(capacity: 1);
        var failedOperation = new OperationContext(failedCapture);
        var nativeFailure = new InvalidOperationException("unchanged despite capture overflow");
        var failingAdapter = new TestAdapter((_, _) => ThrowAsync(nativeFailure));
        var observedFailure = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            CollectAsync(AdapterInvocationBoundary.InvokeAsync(failingAdapter, Request(), failedOperation, EntryRole.Original)));
        Assert.Same(nativeFailure, observedFailure);
        Assert.False(failedCapture.IsAvailable);

        var reusableCapture = new OperationCapture();
        var operationA = new OperationContext(reusableCapture);
        await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request("A"), operationA, EntryRole.Original));
        var preservedEntries = reusableCapture.Entries.ToArray();
        var preservedAssessments = reusableCapture.Assessments.ToArray();
        var preservedLifecycle = reusableCapture.Lifecycle.ToArray();
        var preservedEvents = operationA.LastEntry!.AdapterEvents.ToArray();
        var operationB = new OperationContext(reusableCapture);
        var bDelivery = await CollectAsync(AdapterInvocationBoundary.InvokeAsync(adapter, Request("B"), operationB, EntryRole.Original));

        Assert.Equal(events, bDelivery);
        Assert.False(reusableCapture.IsAvailable);
        Assert.Contains("capture was reused by a different operation", reusableCapture.UnavailableReasons);
        Assert.Equal(preservedEntries, reusableCapture.Entries);
        Assert.Equal(preservedAssessments, reusableCapture.Assessments);
        Assert.Equal(preservedLifecycle, reusableCapture.Lifecycle);
        Assert.Equal(preservedEvents, operationA.LastEntry.AdapterEvents);
        Assert.Empty(operationB.LastEntry!.AdapterEvents);
        Assert.Equal(0, adapter.DisposeCalls);
    }

    private static WireRequest Request(string model = "fixture:model", double timeoutS = 120, int maxResponseBytes = 1_048_576) =>
        new(model, [new Message("user", [new Text("native lifecycle")])], new Sampling(), stream: false, timeoutS: timeoutS, maxResponseBytes: maxResponseBytes);

    private static async Task<List<AdapterEvent>> CollectAsync(IAsyncEnumerable<AdapterEvent> stream)
    {
        var result = new List<AdapterEvent>();
        await foreach (var item in stream)
        {
            result.Add(item);
        }

        return result;
    }

    private static async IAsyncEnumerable<AdapterEvent> YieldAsync(
        [EnumeratorCancellation] CancellationToken token,
        params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> ThrowAsync(Exception failure)
    {
        await Task.Yield();
        if (failure is null)
        {
            yield return new AdapterFinal("unreachable");
            yield break;
        }

        throw failure;
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockUntilCancelledAsync([EnumeratorCancellation] CancellationToken token)
    {
        await Task.Delay(Timeout.InfiniteTimeSpan, token);
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> FinalThenBlockedCleanupAsync([EnumeratorCancellation] CancellationToken token)
    {
        try
        {
            yield return new AdapterFinal("stop");
        }
        finally
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> FinalThenCleanupFailureAsync([EnumeratorCancellation] CancellationToken token, Exception failure)
    {
        try
        {
            token.ThrowIfCancellationRequested();
            yield return new AdapterFinal("stop");
        }
        finally
        {
            await Task.Yield();
            throw failure;
        }
    }

    private static void AssertLifecycle(EntryContext entry, OperationCapture capture, params string[] expectedNames)
    {
        var observations = capture.Lifecycle.Where(item => item.EntryOrdinal == entry.Ordinal).ToArray();
        Assert.Equal(expectedNames, observations.Select(item => item.Name));
        Assert.Equal(Enumerable.Range(0, observations.Length).Select(static index => (long)index), observations.Select(item => item.Sequence));
    }

    private static void AssertLifecycleTail(EntryContext entry, OperationCapture capture, params string[] expectedNames)
    {
        var observations = capture.Lifecycle.Where(item => item.EntryOrdinal == entry.Ordinal).ToArray();
        Assert.True(observations.Length >= expectedNames.Length);
        Assert.Equal(expectedNames, observations.TakeLast(expectedNames.Length).Select(item => item.Name));
        Assert.Equal(Enumerable.Range(0, observations.Length).Select(static index => (long)index), observations.Select(item => item.Sequence));
    }

    private sealed class TestAdapter : IProviderAdapter
    {
        private readonly Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> _streamFactory;

        internal TestAdapter(Func<WireRequest, CancellationToken, IAsyncEnumerable<AdapterEvent>> streamFactory)
        {
            _streamFactory = streamFactory;
        }

        internal List<WireRequest> Requests { get; } = [];
        internal List<CancellationToken> GenerateTokens { get; } = [];
        internal List<CancellationToken> EnumeratorTokens { get; } = [];
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            GenerateTokens.Add(cancellationToken);
            return new TokenRecordingEnumerable(this, _streamFactory(request, cancellationToken));
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class TokenRecordingEnumerable : IAsyncEnumerable<AdapterEvent>
    {
        private readonly TestAdapter _adapter;
        private readonly IAsyncEnumerable<AdapterEvent> _inner;

        internal TokenRecordingEnumerable(TestAdapter adapter, IAsyncEnumerable<AdapterEvent> inner)
        {
            _adapter = adapter;
            _inner = inner;
        }

        public IAsyncEnumerator<AdapterEvent> GetAsyncEnumerator(CancellationToken cancellationToken = default)
        {
            _adapter.EnumeratorTokens.Add(cancellationToken);
            return _inner.GetAsyncEnumerator(cancellationToken);
        }
    }

    private sealed class DualFailureEnumerable : IAsyncEnumerable<AdapterEvent>
    {
        private readonly Exception _moveFailure;
        private readonly Exception _cleanupFailure;

        internal DualFailureEnumerable(Exception moveFailure, Exception cleanupFailure)
        {
            _moveFailure = moveFailure;
            _cleanupFailure = cleanupFailure;
        }

        public IAsyncEnumerator<AdapterEvent> GetAsyncEnumerator(CancellationToken cancellationToken = default) =>
            new DualFailureEnumerator(_moveFailure, _cleanupFailure);
    }

    private sealed class DualFailureEnumerator : IAsyncEnumerator<AdapterEvent>
    {
        private readonly Exception _moveFailure;
        private readonly Exception _cleanupFailure;

        internal DualFailureEnumerator(Exception moveFailure, Exception cleanupFailure)
        {
            _moveFailure = moveFailure;
            _cleanupFailure = cleanupFailure;
        }

        public AdapterEvent Current => throw new InvalidOperationException("Current is unavailable after MoveNext failure.");

        public ValueTask<bool> MoveNextAsync() => ValueTask.FromException<bool>(_moveFailure);

        public ValueTask DisposeAsync() => ValueTask.FromException(_cleanupFailure);
    }
}
