using System.Runtime.CompilerServices;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

public sealed class RoutingTests
{
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Buffered_generation_preserves_public_parts_but_joins_frozen_parts_while_normalizing_sampling_and_effective_wire_limits(bool publicSdk)
    {
        var adapter = new ScriptAdapter(static (_, token) => Events(token,
            new AdapterTextDelta("hello"),
            new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3)),
            new AdapterFinal("stop")));
        await using var client = publicSdk
            ? AsyncClient.FromAdapters([new ProviderRegistration("alpha", adapter)])
            : new AsyncClient([new ProviderRegistration("alpha", adapter)], new VirtualClock());
        var request = Request(
            messages:
            [
                new Message("system", [new Text("keep")]),
                new Message("user", [new Text("hel"), new Text("lo")]),
            ],
            sampling: new Sampling(temperature: 0.25, stop: []),
            timeoutS: null,
            maxResponseBytes: null);

        var result = await client.GenerateAsync(request);

        Assert.Equal("hello", result.Text);
        var wire = Assert.Single(adapter.Requests);
        Assert.Equal("model", wire.Model);
        Assert.Equal(120, wire.TimeoutS);
        Assert.Equal(1_048_576, wire.MaxResponseBytes);
        Assert.Null(wire.Sampling.Stop);
        Assert.Equal(2, wire.Messages.Count);
        if (publicSdk)
        {
            Assert.Collection(wire.Messages[1].Content,
                part => Assert.Equal("hel", Assert.IsType<Text>(part).Value),
                part => Assert.Equal("lo", Assert.IsType<Text>(part).Value));
        }
        else
        {
            Assert.Equal("hello", Assert.IsType<Text>(Assert.Single(wire.Messages[1].Content)).Value);
        }
        Assert.Equal(2, result.Usage!.InputTokens);
        Assert.Equal(3, result.Usage.OutputTokens);
    }

    [Fact]
    public async Task Lazy_resolution_allows_a_good_first_target_and_exposes_a_bad_first_target()
    {
        var good = new ScriptAdapter(static (_, token) => Events(token, new AdapterTextDelta("good"), new AdapterFinal("stop")));
        await using var goodClient = Client(new ProviderRegistration("alpha", good));

        var goodResult = await goodClient.GenerateAsync(Request(route: new Route(["alpha:model", "missing:model"])));
        Assert.Equal("good", goodResult.Text);
        Assert.Single(good.Requests);

        await using var badClient = Client(new ProviderRegistration("alpha", good));
        var failure = await Assert.ThrowsAsync<ProviderException>(() =>
            badClient.GenerateAsync(Request(route: new Route(["missing:model", "alpha:model"]))));
        Assert.Equal("configure", failure.Phase);
        Assert.Empty(good.Requests.Skip(1));

        var actualFailure = new ProviderException("real provider failure", "auth", false, "generate");
        var failing = new ScriptAdapter((_, _) => Throw(actualFailure));
        await using var lateInvalidClient = Client(new ProviderRegistration("alpha", failing));
        var late = await Assert.ThrowsAsync<ProviderException>(() =>
            lateInvalidClient.GenerateAsync(Request(route: new Route(["alpha:model", "missing:model"]))));
        Assert.Equal("configure", late.Phase);
        Assert.Single(failing.Requests);
    }

    [Fact]
    public async Task Retry_fallback_health_and_backoff_use_actual_attempts_without_zero_delay_telemetry()
    {
        var firstFailure = new ProviderException("retry", "transport", true, "generate", retryAfterS: 2);
        var failing = new ScriptAdapter((_, _) => Throw(firstFailure));
        var succeeding = new ScriptAdapter(static (_, token) => Events(token, new AdapterTextDelta("fallback"), new AdapterFinal("stop")));
        var clock = new VirtualClock();
        await using var client = Client(
            [new ProviderRegistration("first", failing), new ProviderRegistration("second", succeeding)],
            clock);
        var capture = new OperationCapture();
        var request = Request(route: new Route(["first:model", "second:model"], new Retry(MaxAttempts: 2, BackoffBaseS: 0.5, BackoffMaxS: 1)));

        var result = await client.GenerateAsync(request, capture);

        Assert.Equal("fallback", result.Text);
        Assert.Equal(2, failing.Requests.Count);
        Assert.Single(succeeding.Requests);
        Assert.Equal([1d], clock.Delays);
        Assert.DoesNotContain(clock.Delays, static delay => delay == 0);
        Assert.True(client.Health.IsUnhealthy(new ResolvedTarget("first", "model"), request.Route.HealthTtlS));
        clock.Advance(request.Route.HealthTtlS);
        Assert.False(client.Health.IsUnhealthy(new ResolvedTarget("first", "model"), request.Route.HealthTtlS));
    }

    [Fact]
    public async Task Retryable_failure_records_retried_trail_and_does_not_mark_health_during_backoff()
    {
        var retryable = new ProviderException("retry once", "transport", true, "generate");
        var adapter = new ScriptAdapter((call, token) => call == 1
            ? Throw(retryable)
            : Events(token, new AdapterTextDelta("ok"), new AdapterFinal("stop")));
        var clock = new VirtualClock();
        AsyncClient? client = null;
        clock.OnDelay = _ => Assert.False(client!.Health.IsUnhealthy(new ResolvedTarget("alpha", "model"), 30));
        client = Client([new ProviderRegistration("alpha", adapter)], clock);
        await using (client)
        {
            var stream = client.StreamAsync(Request(stream: true, route: new Route(["alpha:model"], new Retry(MaxAttempts: 2, BackoffBaseS: 1, BackoffMaxS: 1))));
            var events = await Collect(stream);
            Assert.NotNull(stream.Result);
            var result = stream.Result!;
            Assert.Equal(["retried", "ok"], result.Attempts.Select(item => item.Outcome));
            Assert.Same(retryable, result.Attempts[0].Error);
            Assert.False(client.Health.IsUnhealthy(new ResolvedTarget("alpha", "model"), 30));
            var firstStart = events.FindIndex(static item => item is TimingMark attempt && attempt.Name == "attempt_start");
            var failure = events.FindIndex(item => item is AttemptFailed failed && ReferenceEquals(failed.Record.Error, retryable));
            var secondStart = events.FindIndex(firstStart + 1, item => item is TimingMark attempt && attempt.Name == "attempt_start");
            Assert.True(firstStart >= 0 && failure > firstStart && secondStart > failure);
        }
    }

    [Fact]
    public void Uncapped_retry_after_is_a_floor_and_zero_delay_is_not_a_backoff()
    {
        var uncapped = new Retry(MaxAttempts: 2, BackoffBaseS: 0.5, BackoffMaxS: 5);
        Assert.Equal(2, RouteState.BackoffSeconds(uncapped, 1, retryAfterS: 2));
        var zeroBase = new Retry(MaxAttempts: 2, BackoffBaseS: 0, BackoffMaxS: 5);
        Assert.Equal(0, RouteState.BackoffSeconds(zeroBase, 1, retryAfterS: 0));
    }

    [Fact]
    public async Task Health_exact_ttl_expires_and_health_gate_false_allows_success_to_clear_an_early_mark()
    {
        var failure = new ProviderException("temporary", "transport", true, "generate");
        var adapter = new ScriptAdapter((call, token) => call == 1
            ? Throw(failure)
            : Events(token, new AdapterTextDelta("cleared"), new AdapterFinal("stop")));
        var clock = new VirtualClock();
        await using var client = Client([new ProviderRegistration("alpha", adapter)], clock);
        var target = new ResolvedTarget("alpha", "model");
        client.Health.SeedFailure(target, 0);
        clock.Advance(30);
        Assert.False(client.Health.IsUnhealthy(target, 30));

        client.Health.SeedFailure(target, clock.NowSeconds);
        Assert.True(client.Health.IsUnhealthy(target, 30));
        var result = await client.GenerateAsync(Request(route: new Route(["alpha:model"], healthGate: false)));
        Assert.Equal("cleared", result.Text);
        Assert.False(client.Health.IsUnhealthy(target, 30));
    }

    [Fact]
    public async Task Repair_retains_the_actual_assessment_preparation_and_correction_wire_reference()
    {
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        var adapter = new ScriptAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("{\"age\":"), new AdapterTextDelta("\"wrong\"}"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"age\":"), new AdapterTextDelta("7}"), new AdapterFinal("stop")));
        await using var client = Client(new ProviderRegistration("alpha", adapter, maxRepairAttempts: 1));
        var capture = new OperationCapture();

        var stream = client.StreamAsync(Request(schema: schema, repair: new Repair(1)), capture);
        var events = await Collect(stream);
        Assert.NotNull(stream.Result);
        var result = stream.Result!;

        Assert.Equal("{\"age\":7}", result.Text);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Equal(2, adapter.Requests.Count);
        Assert.Equal(2, capture.Assessments.Count);
        var assessment = capture.Assessments[0];
        var preparation = Assert.Single(capture.Repairs);
        Assert.Same(assessment, preparation.Assessment);
        var correction = Assert.Single(capture.Entries, entry => entry.Role == EntryRole.Correction);
        Assert.Same(assessment, correction.RepairAssessment);
        Assert.Same(adapter.Requests[1], correction.Request);
        Assert.Equal("{\"age\":\"wrong\"}", preparation.ResponseText);
        Assert.NotSame(preparation.Messages, correction.Request.Messages);
        Assert.Equal(preparation.Messages.Last().Role, correction.Request.Messages.Last().Role);
        Assert.Equal([1, 2], capture.Assessments.Select(item => item.SourceEntryOrdinal));
        Assert.NotNull(stream.Operation);
        Assert.Same(capture.Assessments[1], stream.Operation!.LastAssessment);
        Assert.Equal(
            ["attempt_start", "first_token", "attempt_start", "first_token"],
            events.OfType<TimingMark>().Select(item => item.Name));
        var timing = events
            .Select((item, index) => (item, index))
            .Where(static item => item.item is TimingMark)
            .Select(static item => item.index)
            .ToArray();
        Assert.True(timing[0] < timing[1] && timing[2] < timing[3]);
        Assert.IsType<TextDelta>(events[timing[1] + 1]);
        Assert.IsType<TextDelta>(events[timing[3] + 1]);
        var repairTelemetry = Assert.Single(capture.Telemetry);
        Assert.Equal("repair_attempted", repairTelemetry.Name);
        Assert.Equal(1, repairTelemetry.AttemptNumber);
    }

    [Fact]
    public async Task Prompt_injection_uses_the_last_system_message_and_preserves_literal_caller_template_text()
    {
        const string literal = "Respond again with ONLY a corrected JSON value that satisfies the schema. No prose, no code fences.";
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        var messages = new[]
        {
            new Message("system", [new Text("first system")]),
            new Message("user", [new Text(literal)]),
            new Message("system", [new Text("last system")]),
        };
        var adapter = new ScriptAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("{\"age\":\"bad\"}"), new AdapterFinal("stop"))
            : Events(token, new AdapterTextDelta("{\"age\":7}"), new AdapterFinal("stop")));
        await using var client = Client(new ProviderRegistration("alpha", adapter));

        await client.GenerateAsync(Request(messages: messages, schema: schema, repair: new Repair(1)));

        Assert.Equal(2, adapter.Requests.Count);
        var originalWire = adapter.Requests[0];
        Assert.Equal("first system", Render(originalWire.Messages[0]));
        Assert.Equal(literal, Render(originalWire.Messages[1]));
        Assert.StartsWith("last system\n\n", Render(originalWire.Messages[2]), StringComparison.Ordinal);
        var correctionWire = adapter.Requests[1];
        Assert.Equal(literal, Render(correctionWire.Messages[1]));
        Assert.Equal("{\"age\":\"bad\"}", Render(correctionWire.Messages[^2]));
        Assert.StartsWith("Your previous response did not match the required JSON schema. Errors:\n", Render(correctionWire.Messages[^1]), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Repair_exhaustion_and_provider_ceiling_leave_actual_telemetry_and_no_synthetic_success()
    {
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        var invalid = new ScriptAdapter(static (_, token) => Events(token, new AdapterTextDelta("{}"), new AdapterFinal("stop")));
        await using var client = Client(new ProviderRegistration("alpha", invalid, maxRepairAttempts: 1));
        var capture = new OperationCapture();

        var failure = await Assert.ThrowsAsync<SchemaViolationException>(() =>
            client.GenerateAsync(Request(schema: schema, repair: new Repair(8)), capture));

        Assert.Equal(2, invalid.Requests.Count);
        Assert.Single(capture.Repairs);
        Assert.Equal(2, capture.Assessments.Count);
        Assert.Equal([1, 2], capture.Assessments.Select(item => item.SourceEntryOrdinal));
        Assert.Same(capture.Assessments[1].Issues[0], failure.Issues[0]);
        Assert.Equal(["parameter_dropped", "repair_attempted"], capture.Telemetry.Select(item => item.Name));
        var dropped = capture.Telemetry[0];
        Assert.Equal("repair.max_attempts", dropped.Parameter);
        Assert.Equal("alpha allows at most 1 schema-repair round trip(s); 8 requested", dropped.Reason);
        Assert.Equal(1, capture.Telemetry[1].AttemptNumber);
    }

    [Theory]
    [InlineData(null)]
    [InlineData(0)]
    [InlineData(-3)]
    public async Task Absent_zero_and_negative_repair_budget_do_not_create_a_correction(int? budget)
    {
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"]}");
        var adapter = new ScriptAdapter(static (_, token) => Events(token, new AdapterTextDelta("{}"), new AdapterFinal("stop")));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var repair = budget is null ? null : new Repair(budget.Value);

        await Assert.ThrowsAsync<SchemaViolationException>(() => client.GenerateAsync(Request(schema: schema, repair: repair)));

        Assert.Single(adapter.Requests);
    }

    [Fact]
    public async Task Correction_transport_failure_restarts_the_original_with_a_fresh_budget_before_winning_correction()
    {
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        var transport = new ProviderException("correction transport", "transport", true, "generate");
        var adapter = new ScriptAdapter((call, token) => call switch
        {
            1 => Events(token, new AdapterTextDelta("{\"age\":\"bad\"}"), new AdapterFinal("stop")),
            2 => Throw(transport),
            3 => Events(token, new AdapterTextDelta("{\"age\":\"bad\"}"), new AdapterFinal("stop")),
            4 => Events(token, new AdapterTextDelta("{\"age\":7}"), new AdapterFinal("stop")),
            _ => throw new InvalidOperationException("unexpected entry"),
        });
        await using var client = Client(new ProviderRegistration("alpha", adapter, maxRepairAttempts: 1));
        var capture = new OperationCapture();

        var result = await client.GenerateAsync(Request(schema: schema, repair: new Repair(3)), capture);

        Assert.Equal("{\"age\":7}", result.Text);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Equal(4, adapter.Requests.Count);
        Assert.Equal([EntryRole.Original, EntryRole.Correction, EntryRole.Original, EntryRole.Correction], capture.Entries.Select(item => item.Role));
        Assert.Equal([1, 2, 3, 4], capture.Entries.Select(item => item.Ordinal));
        Assert.Equal(3, capture.Assessments.Count);
        Assert.Equal(2, capture.Repairs.Count);
        Assert.Equal([1, 3, 4], capture.Assessments.Select(item => item.SourceEntryOrdinal));
        Assert.Same(capture.Assessments[0], capture.Repairs[0].Assessment);
        Assert.Same(capture.Assessments[1], capture.Repairs[1].Assessment);
        Assert.Same(capture.Assessments[0], capture.Entries[1].RepairAssessment);
        Assert.Same(capture.Assessments[1], capture.Entries[3].RepairAssessment);
        Assert.Same(adapter.Requests[0], capture.Entries[0].Request);
        Assert.Same(adapter.Requests[2], capture.Entries[2].Request);
        Assert.Equal(capture.Entries[0].Request.Messages.Select(Render), capture.Entries[2].Request.Messages.Select(Render));
        Assert.Equal(["parameter_dropped", "repair_attempted", "repair_attempted"], capture.Telemetry.Select(item => item.Name));
        Assert.Equal([1, 1], capture.Telemetry.Skip(1).Select(item => item.AttemptNumber));
        Assert.Equal("alpha allows at most 1 schema-repair round trip(s); 3 requested", capture.Telemetry[0].Reason);
    }

    [Fact]
    public async Task Post_content_protocol_failure_is_terminal_but_post_content_transport_can_retry()
    {
        var protocol = new ProviderException("bad framing", "stream_protocol", false, "stream");
        var protocolAdapter = new ScriptAdapter((_, token) => DeltasThenThrow(token, protocol));
        await using var protocolClient = Client(new ProviderRegistration("alpha", protocolAdapter));
        var protocolStream = protocolClient.StreamAsync(Request(stream: true));
        var publicEvents = new List<StreamEvent>();
        var observed = await Assert.ThrowsAsync<ProviderException>(async () =>
        {
            await foreach (var item in protocolStream)
            {
                publicEvents.Add(item);
            }
        });
        Assert.Same(protocol, observed);
        Assert.Single(protocolAdapter.Requests);
        Assert.Null(protocolStream.ObservedResult);
        Assert.DoesNotContain(publicEvents, static item => item is StreamEnded);
        Assert.Contains(publicEvents, static item => item is AttemptFailed);

        var retryable = new ProviderException("cut", "transport", true, "stream");
        var transportAdapter = new ScriptAdapter((call, token) => call == 1
            ? DeltasThenThrow(token, retryable)
            : Events(token, new AdapterTextDelta("recovered"), new AdapterFinal("stop")));
        await using var transportClient = Client(new ProviderRegistration("alpha", transportAdapter));
        var recovered = await transportClient.GenerateAsync(Request(route: new Route(["alpha:model"], new Retry(MaxAttempts: 2))));
        Assert.Equal("recovered", recovered.Text);
        Assert.Equal(2, transportAdapter.Requests.Count);
    }

    [Fact]
    public async Task Protocol_failure_after_correction_text_is_terminal_without_retry_fallback_or_health_mark()
    {
        var schema = JsonReader.Read("{\"type\":\"object\",\"required\":[\"age\"],\"properties\":{\"age\":{\"type\":\"integer\"}}}");
        var protocol = new ProviderException("correction framing", "stream_protocol", false, "stream");
        var primary = new ScriptAdapter((call, token) => call == 1
            ? Events(token, new AdapterTextDelta("{\"age\":\"bad\"}"), new AdapterFinal("stop"))
            : DeltasThenThrow(token, protocol));
        var fallback = new ScriptAdapter(static (_, token) => Events(token, new AdapterTextDelta("unexpected"), new AdapterFinal("stop")));
        var clock = new VirtualClock();
        await using var client = Client([new ProviderRegistration("alpha", primary), new ProviderRegistration("beta", fallback)], clock);
        var stream = client.StreamAsync(Request(
            schema: schema,
            repair: new Repair(1),
            route: new Route(["alpha:model", "beta:model"], new Retry(MaxAttempts: 2))));
        var events = new List<StreamEvent>();

        var observed = await Assert.ThrowsAsync<ProviderException>(async () =>
        {
            await foreach (var item in stream)
            {
                events.Add(item);
            }
        });

        Assert.Same(protocol, observed);
        Assert.Equal(2, primary.Requests.Count);
        Assert.Empty(fallback.Requests);
        Assert.Empty(clock.Delays);
        Assert.False(client.Health.IsUnhealthy(new ResolvedTarget("alpha", "model"), 30));
        var correctionText = events.FindIndex(static item => item is TextDelta delta && delta.Text == "partial");
        var terminalFailure = events.FindIndex(item => item is AttemptFailed failed && ReferenceEquals(failed.Record.Error, protocol));
        Assert.True(correctionText >= 0);
        Assert.True(terminalFailure > correctionText);
        Assert.Equal(events.Count - 1, terminalFailure);
        Assert.IsType<AttemptFailed>(events[terminalFailure]);
        Assert.DoesNotContain(events, static item => item is StreamEnded);
        Assert.Null(stream.ObservedResult);
    }

    [Fact]
    public async Task Failed_usage_is_discarded_and_winning_usage_overlays_without_erasure_or_total_recomputation()
    {
        var failed = new ProviderException("unavailable", "transport", true, "generate");
        var adapter = new ScriptAdapter((call, token) => call == 1
            ? UsageThenThrow(token, new Usage(InputTokens: 99, TotalTokens: 99), failed)
            : Events(token,
                new AdapterUsage(new Usage(InputTokens: 2, OutputTokens: 3, TotalTokens: 500)),
                new AdapterUsage(new Usage(OutputTokens: 4, CacheReadTokens: 5)),
                new AdapterFinal("stop", new Usage(ReasoningTokens: 6, TotalTokens: 500))));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var stream = client.StreamAsync(Request(stream: true, route: new Route(["alpha:model"], new Retry(MaxAttempts: 2))));

        var events = await Collect(stream);
        Assert.NotNull(stream.Result);
        var result = stream.Result!;

        Assert.Equal(2, adapter.Requests.Count);
        Assert.Equal(2, result.Usage!.InputTokens);
        Assert.Equal(4, result.Usage.OutputTokens);
        Assert.Equal(5, result.Usage.CacheReadTokens);
        Assert.Equal(6, result.Usage.ReasoningTokens);
        Assert.Equal(500, result.Usage.TotalTokens);
        Assert.Contains(events, static item => item is AttemptFailed);
        Assert.IsType<StreamEnded>(events[^1]);
        var usageEvents = events.OfType<UsageUpdate>().ToArray();
        Assert.Equal(3, usageEvents.Length);
        Assert.Equal(99, usageEvents[0].Usage.InputTokens);
        Assert.Equal(2, usageEvents[1].Usage.InputTokens);
        Assert.Equal(4, usageEvents[2].Usage.OutputTokens);
    }

    [Fact]
    public async Task Final_only_usage_synthesizes_after_cleanup_but_result_total_is_derived_only_when_missing()
    {
        var finalOnly = new ScriptAdapter(static (_, token) => Events(token,
            new AdapterTextDelta("done"),
            new AdapterFinal("stop", new Usage(InputTokens: 2, OutputTokens: 3))));
        await using var client = Client(new ProviderRegistration("alpha", finalOnly));
        var stream = client.StreamAsync(Request(stream: true));

        var events = await Collect(stream);
        Assert.NotNull(stream.Result);
        var result = stream.Result!;

        Assert.Collection(events,
            item => Assert.IsType<TimingMark>(item),
            item => Assert.IsType<TimingMark>(item),
            item => Assert.IsType<TextDelta>(item),
            item => Assert.IsType<UsageUpdate>(item),
            item => Assert.IsType<StreamEnded>(item));
        var synthetic = Assert.IsType<UsageUpdate>(events[3]).Usage;
        Assert.Equal(2, synthetic.InputTokens);
        Assert.Equal(3, synthetic.OutputTokens);
        Assert.Null(synthetic.TotalTokens);
        Assert.Equal(5, result.Usage!.TotalTokens);

        var stale = new ScriptAdapter(static (_, token) => Events(token,
            new AdapterUsage(new Usage(InputTokens: 1, OutputTokens: 2)),
            new AdapterFinal("stop", new Usage(InputTokens: 5))));
        await using var staleClient = Client(new ProviderRegistration("beta", stale));
        var staleStream = staleClient.StreamAsync(Request(stream: true, route: new Route(["beta:model"])));
        var staleEvents = await Collect(staleStream);
        Assert.NotNull(staleStream.Result);
        var staleResult = staleStream.Result!;
        Assert.Equal(5, staleResult.Usage!.InputTokens);
        Assert.Equal(2, staleResult.Usage.OutputTokens);
        Assert.Equal(7, staleResult.Usage.TotalTokens);
        Assert.Single(staleEvents.OfType<UsageUpdate>());
    }

    [Fact]
    public async Task Native_caller_cancellation_after_entry_and_client_close_await_iterator_cleanup_once()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptAdapter((_, token) => BlockAfterEntry(token, entered, cleaned));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        using var caller = new CancellationTokenSource();
        var capture = new OperationCapture();
        var stream = client.StreamAsync(Request(stream: true), capture, caller.Token);
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var pending = Collect(stream, item =>
        {
            if (item is TimingMark)
            {
                started.TrySetResult();
            }
        });
        await entered.Task;
        await started.Task;
        Assert.False(Assert.Single(capture.Entries).Timeout.IsDisposed);
        caller.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        await cleaned.Task;
        Assert.Single(adapter.Requests);
        Assert.Null(stream.ObservedResult);

        var closingEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var closingCleaned = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var closingAdapter = new ScriptAdapter((_, token) => BlockAfterEntry(token, closingEntered, closingCleaned));
        var closingClient = Client(new ProviderRegistration("beta", closingAdapter));
        var active = closingClient.StreamAsync(Request(stream: true, route: new Route(["beta:model"])));
        var activeRead = Collect(active);
        await closingEntered.Task;
        await closingClient.DisposeAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => activeRead);
        await closingCleaned.Task;
        Assert.Equal(1, closingAdapter.DisposeCalls);
    }

    [Fact]
    public async Task First_public_events_are_delivered_while_native_entry_remains_unreleased()
    {
        var firstNativeText = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptAdapter((_, token) => FirstThenBlockedThenFinal(token, firstNativeText, release));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var capture = new OperationCapture();
        var stream = client.StreamAsync(Request(stream: true, timeoutS: 10), capture);
        await using var enumerator = stream.GetAsyncEnumerator();

        var firstMove = enumerator.MoveNextAsync().AsTask();
        await firstNativeText.Task;
        Assert.True(firstMove.IsCompleted);
        Assert.True(await firstMove);
        Assert.IsType<TimingMark>(enumerator.Current);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.IsType<TimingMark>(enumerator.Current);
        Assert.True(await enumerator.MoveNextAsync());
        Assert.Equal("first", Assert.IsType<TextDelta>(enumerator.Current).Text);
        var entry = Assert.Single(capture.Entries);
        Assert.False(entry.Timeout.IsDisposed);
        Assert.Empty(capture.Assessments);
        Assert.Null(stream.ObservedResult);

        release.TrySetResult();
        var remaining = new List<StreamEvent>();
        while (await enumerator.MoveNextAsync())
        {
            remaining.Add(enumerator.Current);
        }

        Assert.Contains(remaining, static item => item is TextDelta delta && delta.Text == "second");
        Assert.IsType<StreamEnded>(remaining[^1]);
        Assert.Equal("firstsecond", stream.Result!.Text);
    }

    [Fact]
    public async Task Client_close_continues_all_resource_cleanup_when_one_active_iterator_cleanup_throws()
    {
        var failingEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var otherEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanup = new InvalidOperationException("active cleanup failure");
        var failing = new ScriptAdapter((_, token) => FirstThenBlockedCleanupFailure(token, failingEntered, cleanup));
        var other = new ScriptAdapter((_, token) => BlockAfterEntry(token, otherEntered, new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously)));
        var client = Client([new ProviderRegistration("alpha", failing), new ProviderRegistration("beta", other)]);
        var failingRead = Collect(client.StreamAsync(Request(stream: true, route: new Route(["alpha:model"]))));
        var otherRead = Collect(client.StreamAsync(Request(stream: true, route: new Route(["beta:model"]))));
        await failingEntered.Task;
        await otherEntered.Task;

        var observed = await Assert.ThrowsAsync<InvalidOperationException>(() => client.DisposeAsync().AsTask());
        Assert.Same(cleanup, observed);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => otherRead);
        await Assert.ThrowsAsync<InvalidOperationException>(() => failingRead);
        Assert.Equal(1, failing.DisposeCalls);
        Assert.Equal(1, other.DisposeCalls);
    }

    [Fact]
    public async Task Client_close_waits_for_native_cleanup_release_before_disposing_entry_resources()
    {
        var contentDelivered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseCleanup = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var adapter = new ScriptAdapter((_, token) => FirstThenReleaseControlledCleanup(token, contentDelivered, cleanupEntered, releaseCleanup));
        var client = Client(new ProviderRegistration("alpha", adapter));
        var capture = new OperationCapture();
        var stream = client.StreamAsync(Request(stream: true), capture);
        var read = Collect(stream);
        await contentDelivered.Task;

        var close = client.DisposeAsync().AsTask();
        await cleanupEntered.Task;
        var concurrentClientClose = client.DisposeAsync().AsTask();
        var firstStreamClose = stream.DisposeAsync().AsTask();
        var secondStreamClose = stream.DisposeAsync().AsTask();
        var entry = Assert.Single(capture.Entries);
        Assert.False(close.IsCompleted);
        Assert.False(concurrentClientClose.IsCompleted);
        Assert.False(firstStreamClose.IsCompleted);
        Assert.False(secondStreamClose.IsCompleted);
        Assert.False(entry.Timeout.IsDisposed);
        Assert.Equal(0, adapter.DisposeCalls);
        releaseCleanup.TrySetResult();

        await close;
        await concurrentClientClose;
        await firstStreamClose;
        await secondStreamClose;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => read);
        Assert.True(entry.Timeout.IsDisposed);
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_start"));
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_end"));
        Assert.Equal(1, adapter.DisposeCalls);
    }

    [Fact]
    public async Task Cleanup_failure_after_final_prevents_assessment_usage_synthesis_and_success_publication()
    {
        var cleanup = new InvalidOperationException("cleanup after final");
        var adapter = new ScriptAdapter((_, token) => FinalThenCleanupFailure(token, cleanup));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var capture = new OperationCapture();
        var stream = client.StreamAsync(
            Request(schema: JsonReader.Read("{\"type\":\"object\"}"), stream: true),
            capture);
        var publicEvents = new List<StreamEvent>();

        var observed = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
        {
            await foreach (var item in stream)
            {
                publicEvents.Add(item);
            }
        });

        Assert.Same(cleanup, observed);
        Assert.Null(stream.ObservedResult);
        Assert.Empty(capture.Assessments);
        Assert.Empty(capture.Repairs);
        var entry = Assert.Single(capture.Entries);
        Assert.Same(cleanup, entry.NativeFailure);
        Assert.Same(cleanup, entry.TerminalFailure);
        Assert.DoesNotContain(publicEvents, static item => item is UsageUpdate or StreamEnded);
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_start"));
        Assert.Equal(1, capture.Lifecycle.Count(item => item.Name == "cleanup_end"));
    }

    [Fact]
    public async Task Provider_cleanup_failure_after_final_becomes_the_only_attempt_trail_and_never_synthesizes_usage()
    {
        var cleanup = new ProviderException("cleanup transport", "transport", true, "stream");
        var adapter = new ScriptAdapter((_, token) => FinalThenCleanupFailure(token, cleanup));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var stream = client.StreamAsync(Request(stream: true, route: new Route(["alpha:model"], new Retry(MaxAttempts: 1))));
        var events = new List<StreamEvent>();

        var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(async () =>
        {
            await foreach (var item in stream)
            {
                events.Add(item);
            }
        });

        var attempt = Assert.Single(failure.Attempts);
        Assert.Same(cleanup, attempt.Error);
        Assert.Contains(events, static item => item is TextDelta);
        Assert.Contains(events, static item => item is AttemptFailed);
        Assert.DoesNotContain(events, static item => item is UsageUpdate or StreamEnded);
        Assert.Null(stream.ObservedResult);
        Assert.Single(adapter.Requests);
    }

    [Fact]
    public async Task Stream_is_lazy_orders_public_events_and_buffered_consumption_uses_a_fresh_native_operation()
    {
        var adapter = new ScriptAdapter(static (_, token) => Events(token,
            new AdapterTextDelta("a"),
            new AdapterUsage(new Usage(OutputTokens: 1)),
            new AdapterFinal("stop", new Usage(TotalTokens: 4))));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var request = Request(stream: true);
        var stream = client.StreamAsync(request);

        await using (var untouched = stream.GetAsyncEnumerator())
        {
            Assert.Empty(adapter.Requests);
            Assert.Null(stream.ObservedResult);
            Assert.Null(stream.Operation);
        }

        Assert.Null(stream.ObservedResult);
        Assert.Null(stream.Operation);
        var zeroCapture = new OperationCapture();
        var zero = client.StreamAsync(request, zeroCapture);
        await using (var zeroEnumerator = zero.GetAsyncEnumerator())
        {
            Assert.Empty(zeroCapture.Entries);
            Assert.Empty(zeroCapture.Assessments);
            Assert.Empty(zeroCapture.Telemetry);
            Assert.Empty(zeroCapture.Repairs);
            Assert.Null(zero.Operation);
        }
        var live = client.StreamAsync(request);
        var events = await Collect(live);
        Assert.Collection(events,
            item => Assert.IsType<TimingMark>(item),
            item => Assert.IsType<TimingMark>(item),
            item => Assert.IsType<TextDelta>(item),
            item => Assert.IsType<UsageUpdate>(item),
            item => Assert.IsType<StreamEnded>(item));
        Assert.NotNull(live.Result);
        Assert.NotNull(live.Operation);

        var buffered = await client.GenerateAsync(Request());
        Assert.Equal("a", buffered.Text);
        Assert.Equal(2, adapter.Requests.Count);
    }

    [Theory]
    [InlineData("tool")]
    [InlineData("image")]
    public async Task Native_admission_rejects_excluded_raw_content_before_any_adapter_entry(string kind)
    {
        var adapter = new ScriptAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var request = Request(messages:
        [new Message("user", [new UnsupportedContentPart(kind, JsonReader.Read("{}"))])]);

        var failure = await Assert.ThrowsAsync<ProviderException>(() => client.GenerateAsync(request));

        Assert.Equal("unsupported_input", failure.Category);
        Assert.Empty(adapter.Requests);
    }

    [Fact]
    public async Task Native_admission_rejects_every_excluded_raw_family_before_adapter_entry()
    {
        var adapter = new ScriptAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = new AsyncClient([new ProviderRegistration("alpha", adapter)], new VirtualClock());
        var excluded = new GenerationRequest[]
        {
            Request(messages: [new Message("tool", [new Text("raw")])]),
            Request(route: new Route(["alias"])) ,
            Request(schema: JsonReader.Read("{\"unknown\":true}")),
            Request(schema: JsonReader.Read("{\"$ref\":\"#/x\"}")),
            Request(schema: JsonReader.Read("{\"anyOf\":[{}]}")),
            Request(schema: JsonReader.Read("true")),
            Request(schema: JsonReader.Read("{\"$schema\":\"https://example.invalid/dialect\"}")),
        };

        foreach (var request in excluded)
        {
            var failure = await Assert.ThrowsAsync<ProviderException>(() => client.GenerateAsync(request));
            Assert.Equal("unsupported_input", failure.Category);
        }

        Assert.Empty(adapter.Requests);
    }

    [Fact]
    public async Task Construction_invalid_request_precedes_excluded_profile_classification()
    {
        var adapter = new ScriptAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        await using var client = Client(new ProviderRegistration("alpha", adapter));
        var excluded = new Message("tool", [new UnsupportedContentPart("image", JsonReader.Read("{}"))]);

        var negativeSeed = await Assert.ThrowsAsync<ProviderException>(() =>
            client.GenerateAsync(Request(messages: [excluded], sampling: new Sampling(seed: -1))));
        Assert.Equal("invalid_request", negativeSeed.Category);
        Assert.Null(negativeSeed.Phase);
        var nonFinite = await Assert.ThrowsAsync<ProviderException>(() =>
            client.GenerateAsync(Request(messages: [excluded], sampling: new Sampling(presencePenalty: double.NaN))));
        Assert.Equal("invalid_request", nonFinite.Category);
        Assert.Null(nonFinite.Phase);
        Assert.Empty(adapter.Requests);
    }

    [Fact]
    public void Provider_registration_rejects_a_negative_repair_ceiling_but_accepts_null_zero_and_positive()
    {
        var adapter = new ScriptAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        Assert.Throws<ArgumentOutOfRangeException>(() => new ProviderRegistration("negative", adapter, maxRepairAttempts: -1));
        _ = new ProviderRegistration("null", adapter);
        _ = new ProviderRegistration("zero", adapter, maxRepairAttempts: 0);
        _ = new ProviderRegistration("one", adapter, maxRepairAttempts: 1);
    }

    [Fact]
    public async Task Caller_cancellation_fatal_failure_and_client_disposal_preserve_native_lifetime()
    {
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        var blocking = new ScriptAdapter(static (_, token) => Block(token));
        var fatal = new OutOfMemoryException("fatal");
        var fatalAdapter = new ScriptAdapter((_, _) => Throw(fatal));
        var shared = new ScriptAdapter(static (_, token) => Events(token, new AdapterFinal("stop")));
        var client = Client([new ProviderRegistration("block", blocking), new ProviderRegistration("fatal", fatalAdapter), new ProviderRegistration("shared-one", shared), new ProviderRegistration("shared-two", shared)]);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            client.GenerateAsync(Request(route: new Route(["block:model"])), cancelled.Token));
        var observedFatal = await Assert.ThrowsAsync<OutOfMemoryException>(() =>
            client.GenerateAsync(Request(route: new Route(["fatal:model"]))));
        Assert.Same(fatal, observedFatal);

        await client.DisposeAsync();
        Assert.Equal(1, blocking.DisposeCalls);
        Assert.Equal(1, fatalAdapter.DisposeCalls);
        Assert.Equal(1, shared.DisposeCalls);
    }

    private static AsyncClient Client(IEnumerable<ProviderRegistration> providers, IOperationClock? clock = null) =>
        clock is null ? AsyncClient.FromAdapters(providers) : new AsyncClient(providers, clock);

    private static AsyncClient Client(params ProviderRegistration[] providers) => Client((IEnumerable<ProviderRegistration>)providers);

    private static GenerationRequest Request(
        IEnumerable<Message>? messages = null,
        Route? route = null,
        Sampling? sampling = null,
        Repair? repair = null,
        JsonValue? schema = null,
        double? timeoutS = 12.5,
        int? maxResponseBytes = 91,
        bool stream = false) =>
        new(messages ?? [new Message("user", [new Text("routing")])], route ?? new Route(["alpha:model"]), sampling, repair, schema is null ? null : new SchemaSpec(schema, "response"), timeoutS: timeoutS, maxResponseBytes: maxResponseBytes, stream: stream);

    private static async Task<List<StreamEvent>> Collect(AsyncStream stream)
        => await Collect(stream, static _ => { });

    private static async Task<List<StreamEvent>> Collect(AsyncStream stream, Action<StreamEvent> observe)
    {
        var result = new List<StreamEvent>();
        await foreach (var item in stream)
        {
            observe(item);
            result.Add(item);
        }

        return result;
    }

    private static async IAsyncEnumerable<AdapterEvent> Events([EnumeratorCancellation] CancellationToken token, params AdapterEvent[] events)
    {
        foreach (var item in events)
        {
            token.ThrowIfCancellationRequested();
            yield return item;
            await Task.Yield();
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> Throw(Exception? failure)
    {
        await Task.Yield();
        if (failure is null)
        {
            yield break;
        }

        throw failure;
    }

    private static async IAsyncEnumerable<AdapterEvent> Block([EnumeratorCancellation] CancellationToken token)
    {
        await Task.Delay(Timeout.InfiniteTimeSpan, token);
        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> DeltasThenThrow(
        [EnumeratorCancellation] CancellationToken token,
        Exception failure)
    {
        token.ThrowIfCancellationRequested();
        yield return new AdapterTextDelta("partial");
        await Task.Yield();
        throw failure;
    }

    private static async IAsyncEnumerable<AdapterEvent> UsageThenThrow(
        [EnumeratorCancellation] CancellationToken token,
        Usage usage,
        Exception failure)
    {
        token.ThrowIfCancellationRequested();
        yield return new AdapterUsage(usage);
        await Task.Yield();
        throw failure;
    }

    private static async IAsyncEnumerable<AdapterEvent> BlockAfterEntry(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource entered,
        TaskCompletionSource cleaned)
    {
        entered.TrySetResult();
        try
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        finally
        {
            cleaned.TrySetResult();
        }

        yield break;
    }

    private static async IAsyncEnumerable<AdapterEvent> FinalThenCleanupFailure(
        [EnumeratorCancellation] CancellationToken token,
        Exception failure)
    {
        try
        {
            token.ThrowIfCancellationRequested();
            yield return new AdapterTextDelta("partial");
            yield return new AdapterFinal("stop", new Usage(OutputTokens: 3));
        }
        finally
        {
            await Task.Yield();
            throw failure;
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> FirstThenBlockedThenFinal(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource firstNativeText,
        TaskCompletionSource release)
    {
        token.ThrowIfCancellationRequested();
        firstNativeText.TrySetResult();
        yield return new AdapterTextDelta("first");
        await release.Task.WaitAsync(token);
        yield return new AdapterTextDelta("second");
        yield return new AdapterFinal("stop");
    }

    private static async IAsyncEnumerable<AdapterEvent> FirstThenBlockedCleanupFailure(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource entered,
        Exception failure)
    {
        try
        {
            yield return new AdapterTextDelta("first");
            entered.TrySetResult();
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        finally
        {
            throw failure;
        }
    }

    private static async IAsyncEnumerable<AdapterEvent> FirstThenReleaseControlledCleanup(
        [EnumeratorCancellation] CancellationToken token,
        TaskCompletionSource contentDelivered,
        TaskCompletionSource cleanupEntered,
        TaskCompletionSource releaseCleanup)
    {
        try
        {
            yield return new AdapterTextDelta("first");
            contentDelivered.TrySetResult();
            await Task.Delay(Timeout.InfiniteTimeSpan, token);
        }
        finally
        {
            cleanupEntered.TrySetResult();
            await releaseCleanup.Task;
        }
    }

    private static string Render(Message message) => string.Concat(message.Content.OfType<Text>().Select(static part => part.Value));

    private sealed class ScriptAdapter : IProviderAdapter
    {
        private readonly Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> _script;
        private int _calls;

        internal ScriptAdapter(Func<int, CancellationToken, IAsyncEnumerable<AdapterEvent>> script) => _script = script;

        internal List<WireRequest> Requests { get; } = [];
        internal int DisposeCalls { get; private set; }

        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            return _script(Interlocked.Increment(ref _calls), cancellationToken);
        }

        public ValueTask DisposeAsync()
        {
            DisposeCalls++;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class VirtualClock : IOperationClock
    {
        internal List<double> Delays { get; } = [];
        internal Action<double>? OnDelay { get; set; }
        public double NowSeconds { get; private set; }

        public ValueTask DelayAsync(double seconds, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Delays.Add(seconds);
            OnDelay?.Invoke(seconds);
            NowSeconds += seconds;
            return ValueTask.CompletedTask;
        }

        internal void Advance(double seconds) => NowSeconds += seconds;
    }
}
