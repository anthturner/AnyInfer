using AnyInfer;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Conformance;

public sealed class ReleaseAssetsFixtureAdapterTests
{
    [Fact]
    public async Task FixtureAdapter_is_lazy_and_emits_scripted_text_usage_and_final_in_order()
    {
        var adapter = FixtureAdapter.Create(Script("""
        [{"events":[
          {"text":"hello "},
          {"usage":{"input_tokens":2,"output_tokens":3,"total_tokens":5}},
          {"final":{"finish_reason":"other","usage":{"output_tokens":4}}}
        ]}]
        """));
        var enumerable = adapter.GenerateAsync(Request());
        await using var enumerator = enumerable.GetAsyncEnumerator();

        Assert.Equal(0, adapter.CallCount);
        Assert.Equal(1, adapter.RemainingEntries);

        Assert.True(await enumerator.MoveNextAsync());
        var text = Assert.IsType<AdapterTextDelta>(enumerator.Current);
        Assert.Equal("hello ", text.Text);
        Assert.Equal(1, adapter.CallCount);
        Assert.Equal(0, adapter.RemainingEntries);

        Assert.True(await enumerator.MoveNextAsync());
        var usage = Assert.IsType<AdapterUsage>(enumerator.Current);
        Assert.Equal(2, usage.Usage.InputTokens);
        Assert.Equal(3, usage.Usage.OutputTokens);
        Assert.Equal(5, usage.Usage.TotalTokens);

        Assert.True(await enumerator.MoveNextAsync());
        var final = Assert.IsType<AdapterFinal>(enumerator.Current);
        Assert.Equal("other", final.FinishReason);
        Assert.Equal(4, final.Usage!.OutputTokens);
        Assert.False(await enumerator.MoveNextAsync());
    }

    [Fact]
    public async Task FixtureAdapter_distinguishes_an_explicit_null_usage_update_from_a_final_without_usage()
    {
        var adapter = FixtureAdapter.Create(Script("""
        [{"events":[{"usage":null},{"final":{"usage":null}}]}]
        """));
        await using var iterator = adapter.GenerateAsync(Request()).GetAsyncEnumerator();

        Assert.True(await iterator.MoveNextAsync());
        var update = Assert.IsType<AdapterUsage>(iterator.Current);
        Assert.Null(update.Usage.InputTokens);
        Assert.Null(update.Usage.OutputTokens);
        Assert.Null(update.Usage.TotalTokens);

        Assert.True(await iterator.MoveNextAsync());
        var final = Assert.IsType<AdapterFinal>(iterator.Current);
        Assert.Null(final.Usage);
    }

    [Fact]
    public async Task FixtureAdapter_preserves_immediate_and_terminal_provider_failures_with_declared_defaults()
    {
        var immediate = FixtureAdapter.Create(Script("""
        [{"fail":{"category":"auth"}}]
        """));
        var immediateFailure = await Assert.ThrowsAsync<ProviderException>(async () =>
        {
            await foreach (var _ in immediate.GenerateAsync(Request()))
            {
            }
        });
        Assert.Equal("auth", immediateFailure.Category);
        Assert.False(immediateFailure.Retryable);
        Assert.Null(immediateFailure.RetryAfterS);
        Assert.Null(immediateFailure.HttpStatus);
        Assert.Equal("generate", immediateFailure.Phase);

        var terminal = FixtureAdapter.Create(Script("""
        [{"events":[{"text":"prefix"}],"fail":{"category":"transport","retryable":true,"retry_after_s":1.5,"http_status":503,"phase":"stream"}}]
        """));
        await using var iterator = terminal.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await iterator.MoveNextAsync());
        Assert.Equal("prefix", Assert.IsType<AdapterTextDelta>(iterator.Current).Text);
        var terminalFailure = await Assert.ThrowsAsync<ProviderException>(async () =>
            await iterator.MoveNextAsync());
        Assert.Equal("transport", terminalFailure.Category);
        Assert.True(terminalFailure.Retryable);
        Assert.Equal(1.5, terminalFailure.RetryAfterS);
        Assert.Equal(503, terminalFailure.HttpStatus);
        Assert.Equal("stream", terminalFailure.Phase);

        var omittedPhase = FixtureAdapter.Create(Script("""
        [{"events":[{"text":"before-omitted-phase"}],"fail":{"category":"transport"}}]
        """));
        await using var omittedIterator = omittedPhase.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await omittedIterator.MoveNextAsync());
        Assert.Equal("before-omitted-phase", Assert.IsType<AdapterTextDelta>(omittedIterator.Current).Text);
        var omittedFailure = await Assert.ThrowsAsync<ProviderException>(async () =>
            await omittedIterator.MoveNextAsync());
        Assert.Equal("generate", omittedFailure.Phase);
    }

    [Theory]
    [InlineData("rate_limit", true, "generate")]
    [InlineData("provider_unavailable", true, "generate")]
    [InlineData("transport", true, "generate")]
    [InlineData("stream_protocol", false, "stream")]
    public async Task FixtureAdapter_uses_declared_category_defaults(string category, bool retryable, string phase)
    {
        var adapter = FixtureAdapter.Create(Script($$$"""
        [{"fail":{"category":"{{{category}}}"}}]
        """));

        var failure = await Assert.ThrowsAsync<ProviderException>(async () =>
        {
            await foreach (var _ in adapter.GenerateAsync(Request()))
            {
            }
        });
        Assert.Equal(category, failure.Category);
        Assert.Equal(retryable, failure.Retryable);
        Assert.Equal(phase, failure.Phase);
    }

    [Fact]
    public async Task FixtureAdapter_preserves_explicit_failure_overrides_and_requires_closed_executable_envelopes()
    {
        var overridden = FixtureAdapter.Create(Script("""
        [{"fail":{"category":"transport","retryable":false,"retry_after_s":null,"http_status":null,"phase":null}}]
        """));
        var overrideFailure = await Assert.ThrowsAsync<ProviderException>(async () =>
        {
            await foreach (var _ in overridden.GenerateAsync(Request()))
            {
            }
        });
        Assert.False(overrideFailure.Retryable);
        Assert.Null(overrideFailure.RetryAfterS);
        Assert.Null(overrideFailure.HttpStatus);
        Assert.Null(overrideFailure.Phase);

        AssertInvalidScript("""[{"events":[{"text":"x","usage":{}}]}]""");
        AssertInvalidScript("""[{"events":[],"fail":{"category":"auth"},"fail_in_cleanup":{"category":"transport"}}]""");
        AssertInvalidScript("""[{"events":[{"text":"x"}],"fail_in_cleanup":{"category":"transport"}}]""");
        AssertInvalidScript("""[{"fail":{"category":"core_only"}}]""");
        AssertInvalidScript("""[{"fail":{"category":"auth","phase":"not-a-phase"}}]""");
        AssertInvalidScript("""[{"events":[{"final":{"finish_reason":"not-a-reason"}}]}]""");
    }

    [Fact]
    public async Task FixtureAdapter_cleanup_failure_occurs_on_disposal_after_final_and_scripts_exhaustion_is_a_harness_error()
    {
        var cleanup = FixtureAdapter.Create(Script("""
        [{"events":[{"text":"done"},{"final":{"finish_reason":"stop"}}],"fail_in_cleanup":{"category":"transport","retryable":true,"phase":"cleanup"}}]
        """));
        var cleanupIterator = cleanup.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await cleanupIterator.MoveNextAsync());
        Assert.True(await cleanupIterator.MoveNextAsync());
        Assert.IsType<AdapterFinal>(cleanupIterator.Current);
        var cleanupFailure = await Assert.ThrowsAsync<ProviderException>(async () => await cleanupIterator.DisposeAsync());
        Assert.Equal("transport", cleanupFailure.Category);
        Assert.True(cleanupFailure.Retryable);
        Assert.Equal("cleanup", cleanupFailure.Phase);

        var defaultCleanup = FixtureAdapter.Create(Script("""
        [{"events":[{"final":{"finish_reason":"stop"}}],"fail_in_cleanup":{"category":"transport"}}]
        """));
        var defaultIterator = defaultCleanup.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await defaultIterator.MoveNextAsync());
        var defaultFailure = await Assert.ThrowsAsync<ProviderException>(async () => await defaultIterator.DisposeAsync());
        Assert.Equal("generate", defaultFailure.Phase);
        Assert.True(defaultFailure.Retryable);

        var exhausted = FixtureAdapter.Create(Script("""[]"""));
        var exhaustion = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
        {
            await foreach (var _ in exhausted.GenerateAsync(Request()))
            {
            }
        });
        Assert.Contains("exhaust", exhaustion.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task FixtureAdapter_cleanup_failure_requires_that_the_scripted_final_was_actually_emitted()
    {
        const string script = """
        [{"events":[{"text":"before-final"},{"final":{"finish_reason":"stop"}}],"fail_in_cleanup":{"category":"transport"}}]
        """;

        var early = FixtureAdapter.Create(Script(script));
        var earlyIterator = early.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await earlyIterator.MoveNextAsync());
        Assert.Equal("before-final", Assert.IsType<AdapterTextDelta>(earlyIterator.Current).Text);
        await earlyIterator.DisposeAsync();

        var completed = FixtureAdapter.Create(Script(script));
        var completedIterator = completed.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await completedIterator.MoveNextAsync());
        Assert.True(await completedIterator.MoveNextAsync());
        Assert.IsType<AdapterFinal>(completedIterator.Current);
        var failure = await Assert.ThrowsAsync<ProviderException>(async () => await completedIterator.DisposeAsync());
        Assert.Equal("transport", failure.Category);
    }

    [Fact]
    public async Task FixtureAdapter_named_release_gate_observes_cancellation_and_client_owned_disposal()
    {
        var gates = new FixtureGates();
        var adapter = FixtureAdapter.Create(Script("""
        [{"events":[{"await_release":"native-ready"},{"text":"released"},{"final":{}}]}]
        """), gates);
        using var cancelled = new CancellationTokenSource();
        await using var iterator = adapter.GenerateAsync(Request(), cancelled.Token).GetAsyncEnumerator();

        var blockedRead = iterator.MoveNextAsync().AsTask();
        Assert.False(blockedRead.IsCompleted);
        cancelled.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => blockedRead);
        Assert.Equal(1, adapter.CallCount);

        await adapter.DisposeAsync();
        Assert.Throws<ObjectDisposedException>(() => adapter.GenerateAsync(Request()));

        var released = FixtureAdapter.Create(Script("""
        [{"events":[{"await_release":"native-ready"},{"text":"released"},{"final":{}}]}]
        """), gates);
        await using var releasedIterator = released.GenerateAsync(Request()).GetAsyncEnumerator();
        var releasedRead = releasedIterator.MoveNextAsync().AsTask();
        Assert.False(releasedRead.IsCompleted);
        gates.Release("native-ready");
        Assert.True(await releasedRead);
        Assert.Equal("released", Assert.IsType<AdapterTextDelta>(releasedIterator.Current).Text);

        var clientOwned = FixtureAdapter.Create(Script("""
        [{"events":[{"final":{}}]},{"events":[{"text":"second"},{"final":{}}]}]
        """));
        await using (var first = clientOwned.GenerateAsync(Request()).GetAsyncEnumerator())
        {
            Assert.True(await first.MoveNextAsync());
        }

        await using var second = clientOwned.GenerateAsync(Request()).GetAsyncEnumerator();
        Assert.True(await second.MoveNextAsync());
        Assert.Equal("second", Assert.IsType<AdapterTextDelta>(second.Current).Text);
    }

    private static JsonArray Script(string json) => Assert.IsType<JsonArray>(JsonReader.Read(json));

    private static void AssertInvalidScript(string script)
    {
        Assert.Throws<InvalidOperationException>(() => FixtureAdapter.Create(Script(script)));
    }

    private static WireRequest Request() => new(
        "fixture-model",
        [new Message("user", [new Text("fixture request")])],
        new Sampling());
}
