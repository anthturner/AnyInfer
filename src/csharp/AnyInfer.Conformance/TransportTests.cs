using System.Net.Http;
using System.Numerics;
using System.Text;
using AnyInfer;
using AnyInfer.Core;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Conformance;

public sealed class TransportTests : IDisposable
{
    private readonly List<string> _temporaryRoots = [];

    [Fact]
    public async Task Every_inventory_ordered_transport_fixture_executes_from_input_only_and_compares_as_a_native_pass()
    {
        var assets = ReadCopiedAssets();
        var fixtures = TransportFixtures(assets);
        Assert.Equal(11, fixtures.Count);
        Assert.Equal(
            assets.Cases.Where(static item => item.RelativePath?.StartsWith("specification/fixtures/transport/", StringComparison.Ordinal) == true)
                .Select(static item => item.Id),
            fixtures.Select(static fixture => fixture.Case.Id));

        var failures = new List<string>();
        foreach (var fixture in fixtures)
        {
            var input = Assert.IsType<TransportFixtureInput>(fixture.Input);
            TransportRun run;
            try
            {
                run = await TransportRunner.RunAsync(fixture.Case.Id, input);
            }
            catch (Exception exception)
            {
                failures.Add(fixture.Case.Id + "=runner:" + exception.GetType().Name + ":" + Bounded(exception.Message));
                continue;
            }

            Assert.Same(input, run.Input);
            Assert.True(run.HandlerDisposed);
            Assert.Equal(0, run.RemainingResponses);
            Assert.Equal(run.AdapterCallCount, run.WireRequests.Count);
            Assert.Equal(run.ActualHttpRequestCount, run.Exchanges.Count);
            Assert.All(run.Exchanges, static exchange =>
            {
                Assert.True(exchange.ResponseDisposed);
                Assert.True(exchange.ContentDisposed);
                Assert.Equal(exchange.CreatedStreamCount, exchange.DisposedStreamCount);
                Assert.False(exchange.AutomaticSerializationRequested);
            });

            var comparison = TransportComparison.Compare(fixture, run);
            if (!string.Equals(comparison.Verdict, "pass", StringComparison.Ordinal))
            {
                failures.Add(fixture.Case.Id + "=" + comparison.Verdict + ":" + Bounded(comparison.Detail));
            }
        }

        Assert.True(failures.Count == 0, string.Join("; ", failures));
    }

    [Fact]
    public async Task Core_http_correction_keeps_original_input_and_causal_capture_wire_exchange_identities()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "transport/openai-chat/correction-byte-budget-reset");
        var input = Assert.IsType<TransportFixtureInput>(fixture.Input);

        var run = await TransportRunner.RunAsync(fixture.Case.Id, input);
        var core = Assert.IsType<NativeRun>(run.Core);
        Assert.Equal("pass", TransportComparison.Compare(fixture, run).Verdict);
        Assert.Same(input, run.Input);
        Assert.Equal(2, run.AdapterCallCount);
        Assert.Equal(2, run.ActualHttpRequestCount);
        Assert.Equal(2, run.Exchanges.Count);
        Assert.Equal(2, core.Capture.Entries.Count);
        Assert.Equal(EntryRole.Original, core.Capture.Entries[0].Role);
        Assert.Equal(EntryRole.Correction, core.Capture.Entries[1].Role);
        Assert.All(core.Capture.Entries, static entry =>
        {
            Assert.Equal(120d, entry.Request.TimeoutS);
            Assert.Equal(100, entry.Request.MaxResponseBytes);
            Assert.True(entry.Timeout.IsDisposed);
        });
        Assert.Same(core.Capture.Entries[0].Request, run.WireRequests[0]);
        Assert.Same(core.Capture.Entries[1].Request, run.WireRequests[1]);
        Assert.Same(run.WireRequests[0], run.Exchanges[0].BoundWireRequest);
        Assert.Same(run.WireRequests[1], run.Exchanges[1].BoundWireRequest);
        Assert.Equal([78, 74], run.Exchanges.Select(static exchange => exchange.ConfiguredRawChunks.Sum(static chunk => chunk.Length)));
        Assert.True(run.Exchanges.Sum(static exchange => exchange.ConfiguredRawChunks.Sum(static chunk => chunk.Length)) > 100);

        var repair = Assert.Single(core.Capture.Repairs);
        Assert.Same(repair.Assessment, core.Capture.Entries[1].RepairAssessment);
        Assert.Equal(core.Capture.Entries[0].Ordinal, repair.Assessment.SourceEntryOrdinal);
        Assert.Contains(core.Capture.Assessments, assessment => ReferenceEquals(assessment, repair.Assessment));
        var result = Assert.IsType<GenerationResult>(core.Result);
        Assert.Equal("{\"age\":7}", result.Text);
        Assert.Equal(1, result.RepairAttempts);
        Assert.Equal(new BigInteger(7), Assert.IsType<JsonInteger>(Assert.IsType<JsonObject>(result.Structured).Properties.Single(static property => property.Name == "age").Value).Value);
    }

    [Fact]
    public async Task Direct_adapter_preserves_native_event_order_and_protocol_errors_do_not_emit_a_final()
    {
        var assets = ReadCopiedAssets();
        var singleFixture = Fixture(assets, "transport/openai-chat/single-frame");
        var single = await TransportRunner.RunAsync(
            singleFixture.Case.Id,
            Assert.IsType<TransportFixtureInput>(singleFixture.Input));
        Assert.Equal("pass", TransportComparison.Compare(singleFixture, single).Verdict);
        Assert.Collection(single.DirectEvents,
            item => Assert.Equal("hello", Assert.IsType<AdapterTextDelta>(item).Text),
            item => Assert.Equal(3, Assert.IsType<AdapterUsage>(item).Usage.TotalTokens),
            item => Assert.Equal("stop", Assert.IsType<AdapterFinal>(item).FinishReason));
        Assert.Null(single.TerminalException);

        var overflowFixture = Fixture(assets, "transport/openai-chat/raw-byte-cap-multibyte-utf8");
        var overflow = await TransportRunner.RunAsync(overflowFixture.Case.Id, Assert.IsType<TransportFixtureInput>(overflowFixture.Input));
        Assert.Equal("pass", TransportComparison.Compare(overflowFixture, overflow).Verdict);
        var error = Assert.IsType<ProviderException>(overflow.TerminalException);
        Assert.Equal("stream_protocol", error.Category);
        Assert.False(error.Retryable);
        Assert.Equal("stream", error.Phase);
        Assert.DoesNotContain(overflow.DirectEvents, static item => item is AdapterFinal);
        var exchange = Assert.Single(overflow.Exchanges);
        var configuredChunk = Assert.Single(exchange.ConfiguredRawChunks);
        Assert.Equal(177, configuredChunk.Length);
        Assert.True(configuredChunk.Length > 147);
        var reads = exchange.ActualReadByteCounts.TakeWhile(static count => count > 0).ToArray();
        Assert.NotEmpty(reads);
        Assert.True(reads.Sum() > 147);
        Assert.True(reads.Sum() <= configuredChunk.Length);
        Assert.True(reads.Take(reads.Length - 1).Sum() <= 147);
        var raw = Encoding.UTF8.GetString(exchange.ConfiguredRawChunks.SelectMany(static chunk => chunk.ToArray()).ToArray());
        Assert.True(raw.EnumerateRunes().Count() <= 147);
    }

    [Fact]
    public async Task Protocol_after_content_stays_on_its_actual_entry_without_backup_or_stream_end()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "transport/openai-chat/protocol-error-after-content");
        var run = await TransportRunner.RunAsync(fixture.Case.Id, Assert.IsType<TransportFixtureInput>(fixture.Input));
        var core = Assert.IsType<NativeRun>(run.Core);

        Assert.Equal("pass", TransportComparison.Compare(fixture, run).Verdict);
        Assert.Equal(1, run.ActualHttpRequestCount);
        Assert.Single(run.Exchanges);
        Assert.Single(core.Capture.Entries);
        Assert.Null(core.Result);
        var terminal = Assert.IsType<ProviderException>(core.TerminalException);
        Assert.Equal("stream_protocol", terminal.Category);
        Assert.False(terminal.Retryable);
        Assert.Equal("stream", terminal.Phase);
        var failure = Assert.IsType<AttemptFailedEvent>(core.Events.Last());
        Assert.Same(terminal, failure.Attempt.Error);
        Assert.Same(terminal, Assert.Single(core.Capture.Entries).TerminalFailure);
        var partial = Assert.Single(core.Events.OfType<TextDeltaEvent>());
        Assert.Equal("partial", partial.Text);
        var orderedEvents = core.Events.ToArray();
        Assert.True(Array.IndexOf(orderedEvents, partial) < Array.IndexOf(orderedEvents, failure));
        Assert.DoesNotContain(core.Events, static item => item is StreamEndedEvent);
    }

    [Fact]
    public async Task Direct_usage_omits_only_actual_null_counters_and_retry_after_uses_numeric_control_equality()
    {
        var assets = ReadCopiedAssets();
        var usageFixture = Fixture(assets, "transport/openai-chat/trailing-usage-chunk");
        var usageRun = await TransportRunner.RunAsync(usageFixture.Case.Id, Assert.IsType<TransportFixtureInput>(usageFixture.Input));
        Assert.Equal("pass", TransportComparison.Compare(usageFixture, usageRun).Verdict);

        var usageOutcome = ObjectProperty(usageFixture.Expected, "adapter_outcome");
        var events = ArrayProperty(usageOutcome, "events");
        var omittedNullEvents = new JsonArray(events.Items.Select((item, index) =>
        {
            if (index == 1)
            {
                var usage = ObjectProperty(Assert.IsType<JsonObject>(item), "usage");
                return new JsonObject([new JsonProperty("usage", WithoutProperties(usage, "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"))]);
            }

            if (index == 2)
            {
                var final = Assert.IsType<JsonObject>(item);
                var finalUsage = ObjectProperty(final, "final");
                return new JsonObject([new JsonProperty("final", WithProperty(CloneObject(finalUsage), "usage", WithoutProperties(ObjectProperty(finalUsage, "usage"), "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")))]);
            }

            return CloneValue(item);
        }));
        var nullOmittedExpected = WithProperty(CloneObject(usageFixture.Expected), "adapter_outcome", WithProperty(CloneObject(usageOutcome), "events", omittedNullEvents));
        Assert.Equal("pass", TransportComparison.Compare(new FixtureDocument(usageFixture.Case, usageFixture.Input, nullOmittedExpected), usageRun).Verdict);

        var missingKnownEvents = new JsonArray(omittedNullEvents.Items.Select((item, index) =>
            index == 1
                ? new JsonObject([new JsonProperty("usage", WithoutProperties(ObjectProperty(Assert.IsType<JsonObject>(item), "usage"), "input_tokens"))])
                : CloneValue(item)));
        var missingKnownExpected = WithProperty(CloneObject(usageFixture.Expected), "adapter_outcome", WithProperty(CloneObject(usageOutcome), "events", missingKnownEvents));
        Assert.NotEqual("pass", TransportComparison.Compare(new FixtureDocument(usageFixture.Case, usageFixture.Input, missingKnownExpected), usageRun).Verdict);

        var errorFixture = Fixture(assets, "transport/openai-chat/non-sse-error-body-status-503");
        var errorInput = Assert.IsType<TransportFixtureInput>(errorFixture.Input);
        var retryInput = new TransportFixtureInput(errorInput.Kind, errorInput.Input, new JsonArray([
            new JsonObject([
                new JsonProperty("status", new JsonInteger(429)),
                new JsonProperty("headers", new JsonObject([
                    new JsonProperty("content-type", new JsonString("application/json")),
                    new JsonProperty("retry-after", new JsonString("2")),
                ])),
                new JsonProperty("byte_chunks", new JsonArray([
                    new JsonObject([new JsonProperty("bytes", new JsonString(Convert.ToBase64String(Encoding.UTF8.GetBytes("{\"error\":{}}"))))]),
                ])),
            ]),
        ]));
        var retryRun = await TransportRunner.RunAsync(errorFixture.Case.Id, retryInput);
        var retryError = Assert.IsType<ProviderException>(retryRun.TerminalException);
        Assert.Equal("rate_limit", retryError.Category);
        Assert.Equal(429, retryError.HttpStatus);
        Assert.True(retryError.RetryAfterS is 2d);
        var errorOutcome = ObjectProperty(errorFixture.Expected, "adapter_outcome");
        var errorExpectation = ObjectProperty(errorOutcome, "error");
        var rateLimit = WithProperty(
            WithProperty(
                WithProperty(CloneObject(errorExpectation), "category", new JsonString("rate_limit")),
                "http_status",
                new JsonInteger(429)),
            "retry_after_s",
            new JsonInteger(2));
        var integerExpected = WithProperty(CloneObject(errorFixture.Expected), "adapter_outcome", WithProperty(CloneObject(errorOutcome), "error", rateLimit));
        Assert.Equal("pass", TransportComparison.Compare(new FixtureDocument(errorFixture.Case, retryInput, integerExpected), retryRun).Verdict);
        var binary64Expected = WithProperty(CloneObject(integerExpected), "adapter_outcome", WithProperty(CloneObject(errorOutcome), "error", WithProperty(rateLimit, "retry_after_s", new JsonNumber(2d))));
        Assert.Equal("pass", TransportComparison.Compare(new FixtureDocument(errorFixture.Case, retryInput, binary64Expected), retryRun).Verdict);
        var wrongCategory = WithProperty(CloneObject(integerExpected), "adapter_outcome", WithProperty(CloneObject(errorOutcome), "error", WithProperty(rateLimit, "category", new JsonString("transport"))));
        Assert.NotEqual("pass", TransportComparison.Compare(new FixtureDocument(errorFixture.Case, retryInput, wrongCategory), retryRun).Verdict);
    }

    [Fact]
    public async Task Direct_empty_event_carrier_branch_is_valid_while_native_done_sentinel_still_emits_a_final()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "transport/openai-chat/done-sentinel");
        var input = Assert.IsType<TransportFixtureInput>(fixture.Input);
        var emptyInput = new TransportFixtureInput(input.Kind, input.Input, ResponseScripts("text/event-stream", Encoding.UTF8.GetBytes("data: [DONE]\n\n")));
        var run = await TransportRunner.RunAsync(fixture.Case.Id, emptyInput);

        Assert.Collection(run.DirectEvents, item =>
        {
            var final = Assert.IsType<AdapterFinal>(item);
            Assert.Equal("stop", final.FinishReason);
            Assert.Null(final.Usage);
        });
        Assert.Null(run.TerminalException);
        var emptyCarrier = run with { DirectEvents = Array.Empty<AdapterEvent>(), TerminalException = null };
        var emptyExpected = WithProperty(CloneObject(fixture.Expected), "adapter_outcome", new JsonObject([new JsonProperty("events", new JsonArray([]))]));
        Assert.Equal("pass", TransportComparison.Compare(new FixtureDocument(fixture.Case, emptyInput, emptyExpected), emptyCarrier).Verdict);

        var mismatchedExpected = WithProperty(CloneObject(emptyExpected), "adapter_outcome", new JsonObject([new JsonProperty("events", new JsonArray([
            new JsonObject([new JsonProperty("text_delta", new JsonObject([new JsonProperty("text", new JsonString("unexpected"))]))]),
        ]))]));
        Assert.NotEqual("pass", TransportComparison.Compare(new FixtureDocument(fixture.Case, emptyInput, mismatchedExpected), emptyCarrier).Verdict);
    }

    [Fact]
    public async Task Scripted_handler_requires_a_bound_wire_and_consumes_exactly_one_bound_response()
    {
        var responses = new JsonArray([
            new JsonObject([
                new JsonProperty("status", new JsonInteger(200)),
                new JsonProperty("headers", new JsonObject([new JsonProperty("content-type", new JsonString("application/json"))])),
                new JsonProperty("byte_chunks", new JsonArray([
                    new JsonObject([new JsonProperty("bytes", new JsonString(Convert.ToBase64String(Encoding.UTF8.GetBytes("{}"))))]),
                ])),
            ]),
        ]);
        using var handler = new ScriptedHttpMessageHandler(responses);
        using var client = new HttpClient(handler, disposeHandler: false);
        using var unbound = new HttpRequestMessage(HttpMethod.Post, "https://fixture.invalid/v1/chat/completions")
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        };
        await Assert.ThrowsAsync<TransportHarnessException>(async () => await client.SendAsync(unbound));
        Assert.Equal(1, handler.RemainingResponses);
        Assert.Empty(handler.Exchanges);

        var wire = new WireRequest("fixture-model", [new Message("user", [new TextPart("bound")])], new Sampling());
        handler.BindPendingWire(wire);
        using var request = new HttpRequestMessage(HttpMethod.Post, "https://fixture.invalid/v1/chat/completions")
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        };
        using var response = await client.SendAsync(request);
        Assert.Equal(0, handler.RemainingResponses);
        var exchange = Assert.Single(handler.Exchanges);
        Assert.Same(wire, exchange.BoundWireRequest);
        Assert.Equal(2, handler.ActualRequestCount);
    }

    [Fact]
    public async Task Invalid_response_content_type_is_a_harness_failure_and_disposes_the_unreturned_response()
    {
        var responses = new JsonArray([
            new JsonObject([
                new JsonProperty("status", new JsonInteger(200)),
                new JsonProperty("headers", new JsonObject([new JsonProperty("content-type", new JsonString("@"))])),
                new JsonProperty("byte_chunks", new JsonArray([
                    new JsonObject([new JsonProperty("bytes", new JsonString(Convert.ToBase64String(Encoding.UTF8.GetBytes("{}"))))]),
                ])),
            ]),
        ]);
        var handler = new ScriptedHttpMessageHandler(responses);
        var inner = new OpenAIChatAdapter(new Uri("https://fixture.invalid/v1"), "fixture-token", handler: handler);
        var adapter = new RecordingHttpAdapter(inner, handler);
        var wire = new WireRequest("fixture-model", [new Message("user", [new TextPart("header")])], new Sampling());

        try
        {
            await Assert.ThrowsAsync<TransportHarnessException>(async () =>
            {
                await foreach (var _ in adapter.GenerateAsync(wire))
                {
                }
            });
        }
        finally
        {
            await adapter.DisposeAsync();
        }

        Assert.True(handler.IsDisposed);
        var exchange = Assert.Single(handler.Exchanges);
        Assert.True(exchange.ResponseCreated);
        Assert.True(exchange.ContentCreated);
        Assert.True(exchange.ResponseDisposed);
        Assert.True(exchange.ContentDisposed);
        Assert.Equal(0, exchange.CreatedStreamCount);
        Assert.Equal(0, exchange.DisposedStreamCount);
    }

    [Fact]
    public async Task Expected_only_transport_changes_do_not_change_the_retained_native_execution_facts()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "transport/openai-chat/outbound-buffered-message-projection");
        var input = Assert.IsType<TransportFixtureInput>(fixture.Input);
        var run = await TransportRunner.RunAsync(fixture.Case.Id, input);
        Assert.Equal("pass", TransportComparison.Compare(fixture, run).Verdict);

        var alteredExpected = WithProperty(CloneObject(fixture.Expected), "status", new JsonString("not-observed"));
        var altered = new FixtureDocument(fixture.Case, fixture.Input, alteredExpected);
        Assert.NotEqual("pass", TransportComparison.Compare(altered, run).Verdict);
        Assert.Same(input, run.Input);
        Assert.Single(run.Exchanges);
        Assert.Single(run.WireRequests);
        Assert.Same(run.WireRequests[0], run.Exchanges[0].BoundWireRequest);
    }

    [Fact]
    public async Task Transport_projection_fails_closed_for_mismatched_http_count_and_surplus_scripts_are_harness_errors()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "transport/openai-chat/single-frame");
        var input = Assert.IsType<TransportFixtureInput>(fixture.Input);
        var run = await TransportRunner.RunAsync(fixture.Case.Id, input);
        Assert.Throws<ObservationUnavailableException>(() => TransportProjection.Project(run with
        {
            ActualHttpRequestCount = run.ActualHttpRequestCount + 1,
        }));

        var responses = Assert.IsType<JsonArray>(input.Responses);
        var surplus = new JsonArray(responses.Items.Append(CloneValue(responses.Items[0])));
        var alteredInput = new TransportFixtureInput(input.Kind, input.Input, surplus);
        await Assert.ThrowsAsync<TransportHarnessException>(async () =>
            await TransportRunner.RunAsync(fixture.Case.Id, alteredInput));
    }

    [Fact]
    public async Task Direct_protocol_failure_keeps_raw_prefix_in_run_facts_but_projects_only_the_terminal_error_branch()
    {
        var assets = ReadCopiedAssets();
        var fixture = Fixture(assets, "transport/openai-chat/raw-byte-cap-multibyte-utf8");
        var input = Assert.IsType<TransportFixtureInput>(fixture.Input);
        var payload = "data: {\"choices\":[{\"delta\":{\"content\":\"partial\"}}]}\n\ndata: {not-json}\n\n";
        var responses = ResponseScripts("text/event-stream", Encoding.UTF8.GetBytes(payload));
        var protocolInput = new TransportFixtureInput(input.Kind, input.Input, responses);
        var run = await TransportRunner.RunAsync(fixture.Case.Id, protocolInput);

        Assert.Collection(run.DirectEvents, item => Assert.Equal("partial", Assert.IsType<AdapterTextDelta>(item).Text));
        var error = Assert.IsType<ProviderException>(run.TerminalException);
        Assert.Equal("stream_protocol", error.Category);
        Assert.DoesNotContain(run.DirectEvents, static item => item is AdapterFinal);
        var projected = TransportProjection.Project(run);
        var outcome = ObjectProperty(projected, "adapter_outcome");
        Assert.True(outcome.TryGetValue("error", out _));
        Assert.False(outcome.TryGetValue("events", out _));
        Assert.Equal("pass", TransportComparison.Compare(new FixtureDocument(fixture.Case, protocolInput, fixture.Expected), run).Verdict);

        var expectedOutcome = ObjectProperty(fixture.Expected, "adapter_outcome");
        var both = WithProperty(CloneObject(expectedOutcome), "events", new JsonArray([]));
        var neither = WithoutProperties(expectedOutcome, "error");
        Assert.Equal("error", TransportComparison.Compare(new FixtureDocument(fixture.Case, fixture.Input, WithProperty(CloneObject(fixture.Expected), "adapter_outcome", both)), run).Verdict);
        Assert.Equal("error", TransportComparison.Compare(new FixtureDocument(fixture.Case, fixture.Input, WithProperty(CloneObject(fixture.Expected), "adapter_outcome", neither)), run).Verdict);
    }

    [Theory]
    [InlineData("driver/timeout-cleanup-disposal")]
    [InlineData("driver/http-correction-byte-budget-reset")]
    public async Task Final_transport_proofs_dispatch_to_finite_recipe_bound_evidence(string recipeRef)
    {
        Assert.True(NativeProofs.IsSupported(recipeRef));
        var proof = await NativeProofs.RunAsync(recipeRef);
        Assert.Equal("pass", proof.Verdict);
        Assert.Equal(recipeRef, StringProperty(proof.Evidence, "recipe_ref"));
        Assert.NotEmpty(proof.Evidence.Properties);
        AssertOrdinary(proof.Evidence);
    }

    [Fact]
    public async Task Cleanup_timeout_proof_retains_actual_timeout_mapping_trail_and_disposal_facts()
    {
        var proof = await NativeProofs.RunAsync("driver/timeout-cleanup-disposal");
        Assert.Equal("pass", proof.Verdict);
        var evidence = proof.Evidence;
        Assert.True(BooleanProperty(evidence, "capture_available"));
        Assert.True(BooleanProperty(evidence, "cleanup_ready"));
        Assert.True(BooleanProperty(evidence, "adapter_disposed"));
        Assert.True(BooleanProperty(evidence, "native_to_provider"));
        Assert.True(BooleanProperty(evidence, "provider_to_attempt"));
        Assert.Equal(BigInteger.Zero, IntegerProperty(evidence, "assessment_count"));
        var entry = ObjectProperty(evidence, "entry");
        Assert.True(BooleanProperty(entry, "expired"));
        Assert.True(BooleanProperty(entry, "disposed"));
        Assert.NotEmpty(StringProperty(entry, "native_failure"));
        Assert.Equal("ProviderException", StringProperty(entry, "terminal_failure"));
        Assert.Equal("AllTargetsFailedException", StringProperty(evidence, "terminal"));
        var nativeCleanup = ObjectProperty(evidence, "native_cleanup");
        Assert.True(BooleanProperty(nativeCleanup, "final_captured"));
        Assert.False(BooleanProperty(nativeCleanup, "expired_before"));
        Assert.False(BooleanProperty(nativeCleanup, "disposed_before"));
        Assert.False(BooleanProperty(nativeCleanup, "token_requested_before"));
        Assert.Equal("entered", StringProperty(nativeCleanup, "last_lifecycle_before"));
        Assert.True(BooleanProperty(nativeCleanup, "expired_after"));
        Assert.False(BooleanProperty(nativeCleanup, "disposed_after"));
        Assert.True(BooleanProperty(nativeCleanup, "token_requested_after"));
        Assert.Equal("expired", StringProperty(nativeCleanup, "last_lifecycle_after"));
        var attempts = ArrayProperty(evidence, "attempts");
        var attempt = Assert.IsType<JsonObject>(Assert.Single(attempts.Items));
        Assert.Equal("failed", StringProperty(attempt, "outcome"));
        Assert.Equal("transport", StringProperty(attempt, "error"));
        var publicEvents = ArrayProperty(evidence, "public_events").Items.Select(static item => Assert.IsType<JsonString>(item).Value).ToArray();
        Assert.DoesNotContain(nameof(UsageEvent), publicEvents);
        Assert.DoesNotContain(nameof(StreamEndedEvent), publicEvents);
        Assert.Equal(
            ["created", "configured", "entered", "expired", "cleanup_start", "cleanup_end", "exited", "disposed"],
            ArrayProperty(evidence, "lifecycle").Items.Select(static item => StringProperty(Assert.IsType<JsonObject>(item), "name")));
    }

    [Fact]
    public async Task Http_correction_proof_retains_per_entry_raw_byte_and_overflow_facts()
    {
        var proof = await NativeProofs.RunAsync("driver/http-correction-byte-budget-reset");
        Assert.Equal("pass", proof.Verdict);
        var evidence = proof.Evidence;
        Assert.Equal("{\"age\":7}", StringProperty(evidence, "correction_result"));
        Assert.IsType<JsonNull>(ValueProperty(evidence, "correction_terminal"));
        Assert.Equal(BigInteger.One, IntegerProperty(evidence, "correction_repair_attempts"));
        var entries = ArrayProperty(evidence, "correction_entries").Items.Select(Assert.IsType<JsonObject>).ToArray();
        Assert.Equal(2, entries.Length);
        Assert.Equal([BigInteger.One, new BigInteger(2)], entries.Select(static item => IntegerProperty(item, "ordinal")));
        Assert.Equal(["original", "correction"], entries.Select(static item => StringProperty(item, "role")));
        Assert.All(entries, static item => Assert.True(BooleanProperty(item, "disposed")));
        var assessments = ArrayProperty(evidence, "correction_assessments").Items.Select(Assert.IsType<JsonObject>).ToArray();
        Assert.Equal(2, assessments.Length);
        Assert.Equal([BigInteger.One, new BigInteger(2)], assessments.Select(static item => IntegerProperty(item, "source_entry")));
        var repairs = ArrayProperty(evidence, "correction_repairs").Items.Select(Assert.IsType<JsonObject>).ToArray();
        var repair = Assert.Single(repairs);
        Assert.Equal(StringProperty(assessments[0], "id"), StringProperty(repair, "assessment_id"));
        Assert.Equal("{\"age\":\"x\"}", StringProperty(repair, "response"));
        Assert.NotEmpty(ArrayProperty(repair, "messages").Items);
        var exchanges = ArrayProperty(evidence, "http_exchanges").Items.Select(Assert.IsType<JsonObject>).ToArray();
        Assert.Equal(2, exchanges.Length);
        Assert.Equal([BigInteger.Zero, BigInteger.One], exchanges.Select(static exchange => IntegerProperty(exchange, "ordinal")));
        Assert.Equal([78, 74], exchanges.Select(static exchange => ArrayProperty(exchange, "raw_chunk_bytes").Items.Select(static item => Assert.IsType<JsonInteger>(item)).Sum(static value => (int)value.Value)));
        foreach (var name in new[] { "buffered_overflow", "streaming_overflow" })
        {
            var overflow = ObjectProperty(evidence, name);
            Assert.Equal("stream_protocol", StringProperty(overflow, "error_category"));
            Assert.Equal("stream", StringProperty(overflow, "error_phase"));
            Assert.True(BooleanProperty(overflow, "handler_disposed"));
            var exchange = ObjectProperty(overflow, "exchange");
            Assert.True(IntegerProperty(overflow, "raw_code_points") <= new BigInteger(80));
            Assert.True(ArrayProperty(exchange, "raw_chunk_bytes").Items.Select(static item => Assert.IsType<JsonInteger>(item)).Aggregate(BigInteger.Zero, static (sum, value) => sum + value.Value) > new BigInteger(80));
            Assert.All(ArrayProperty(exchange, "raw_chunk_bytes").Items.Select(static item => Assert.IsType<JsonInteger>(item)), static item => Assert.True(item.Value <= new BigInteger(80)));
            Assert.DoesNotContain(ArrayProperty(overflow, "events").Items, static item => Assert.IsType<JsonString>(item).Value == nameof(AdapterFinal));
        }
    }

    public void Dispose()
    {
        foreach (var root in _temporaryRoots)
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private ReleaseAssets ReadCopiedAssets()
    {
        var source = FindSourceSpecificationRoot();
        var destination = Path.Combine(Path.GetTempPath(), "anyinfer-transport-" + Guid.NewGuid().ToString("N"));
        CopyDirectory(source, destination);
        _temporaryRoots.Add(destination);
        return ReleaseAssetsReader.ReadAndVerify(destination, "releases/core-generation-v0.json");
    }

    private static IReadOnlyList<FixtureDocument> TransportFixtures(ReleaseAssets assets) =>
        FixtureReader.ReadFixtures(assets).Where(static fixture => fixture.Input is TransportFixtureInput).ToArray();

    private static FixtureDocument Fixture(ReleaseAssets assets, string id) =>
        Assert.Single(TransportFixtures(assets), fixture => string.Equals(fixture.Case.Id, id, StringComparison.Ordinal));

    private static string StringProperty(JsonObject source, string name) =>
        Assert.IsType<JsonString>(ValueProperty(source, name)).Value;

    private static bool BooleanProperty(JsonObject source, string name) =>
        Assert.IsType<JsonBoolean>(ValueProperty(source, name)).Value;

    private static BigInteger IntegerProperty(JsonObject source, string name) =>
        Assert.IsType<JsonInteger>(ValueProperty(source, name)).Value;

    private static JsonValue ValueProperty(JsonObject source, string name) =>
        source.TryGetValue(name, out var value)
            ? value
            : throw new Xunit.Sdk.XunitException("Missing transport evidence property '" + name + "'.");

    private static JsonObject ObjectProperty(JsonObject source, string name) => Assert.IsType<JsonObject>(ValueProperty(source, name));

    private static JsonArray ArrayProperty(JsonObject source, string name) => Assert.IsType<JsonArray>(ValueProperty(source, name));

    private static void AssertOrdinary(JsonValue value)
    {
        switch (value)
        {
            case JsonNull or JsonBoolean or JsonString or JsonInteger:
                return;
            case JsonNumber number:
                Assert.True(double.IsFinite(number.Value));
                return;
            case JsonArray array:
                foreach (var item in array.Items) AssertOrdinary(item);
                return;
            case JsonObject obj:
                foreach (var property in obj.Properties) AssertOrdinary(property.Value);
                return;
            default:
                throw new Xunit.Sdk.XunitException("Transport evidence contained a non-ordinary JSON value.");
        }
    }

    private static string Bounded(string? detail) => detail is null ? string.Empty : detail.Length <= 160 ? detail : detail[..160];

    private static JsonObject CloneObject(JsonObject source) => Assert.IsType<JsonObject>(JsonReader.Read(JsonWriter.Write(source)));

    private static JsonValue CloneValue(JsonValue source) => JsonReader.Read(JsonWriter.Write(source));

    private static JsonObject WithProperty(JsonObject source, string name, JsonValue value)
    {
        var replaced = false;
        var properties = source.Properties.Select(property =>
        {
            if (!string.Equals(property.Name, name, StringComparison.Ordinal)) return property;
            replaced = true;
            return new JsonProperty(name, value);
        }).ToList();
        if (!replaced) properties.Add(new JsonProperty(name, value));
        return new JsonObject(properties);
    }

    private static JsonObject WithoutProperties(JsonObject source, params string[] names) =>
        new(source.Properties.Where(property => !names.Contains(property.Name, StringComparer.Ordinal)));

    private static JsonArray ResponseScripts(string contentType, byte[] bytes) => new([
        new JsonObject([
            new JsonProperty("status", new JsonInteger(200)),
            new JsonProperty("headers", new JsonObject([new JsonProperty("content-type", new JsonString(contentType))])),
            new JsonProperty("byte_chunks", new JsonArray([
                new JsonObject([new JsonProperty("bytes", new JsonString(Convert.ToBase64String(bytes)))]),
            ])),
        ]),
    ]);

    private static string FindSourceSpecificationRoot()
    {
        foreach (var start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            for (var current = new DirectoryInfo(start); current is not null; current = current.Parent)
            {
                var candidate = Path.Combine(current.FullName, "specification", "releases", "core-generation-v0.json");
                if (File.Exists(candidate)) return Path.GetDirectoryName(Path.GetDirectoryName(candidate))!;
            }
        }

        throw new InvalidOperationException("The source specification tree could not be located.");
    }

    private static void CopyDirectory(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source, "*", SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(Path.Combine(destination, Path.GetRelativePath(source, directory)));
        }

        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            File.Copy(file, Path.Combine(destination, Path.GetRelativePath(source, file)));
        }
    }
}
