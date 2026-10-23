using System.Net;
using System.Collections.Concurrent;
using System.Runtime.ExceptionServices;
using System.Text;
using AnyInfer.Capabilities;
using AnyInfer.Events;
using AnyInfer.Providers;
using AnyInfer.Routing;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public HTTP controls for per-instance transport governance.</summary>
public sealed class GovernedTransportTests
{
    private static readonly RateLimitHeaders HeaderDialect = new(
        requestsRemaining: "x-remaining",
        requestsReset: "x-reset",
        limitRequests: "x-limit");

    [Fact]
    public async Task Redirect_hops_each_acquire_and_release_the_governed_transport_slot()
    {
        var handler = new RedirectThenSuccessHandler();
        var events = new Collector();
        await using var client = CreateClient(
            [Settings("alpha", handler, new RateLimits(maxConcurrent: 1))], events);

        var result = await client.GenerateAsync("redirect", target: "alpha:model");

        Assert.Equal("ok", result.Text);
        Assert.Equal(2, handler.SendCalls);
        Assert.Equal(2, events.Events.OfType<RateLimitObserved>().Count());
    }

    [Fact]
    public async Task Configured_limiters_are_isolated_per_instance_and_observe_merged_response_headers()
    {
        var alpha = new BlockingHandler();
        var beta = new BlockingHandler();
        var events = new Collector();
        await using var client = CreateClient(
            [
                Settings("alpha", alpha, new RateLimits(maxConcurrent: 1)),
                Settings("beta", beta, new RateLimits(maxConcurrent: 1)),
            ],
            events);

        try
        {
            var firstAlpha = client.GenerateAsync("one", target: "alpha:model");
            var betaRequest = client.GenerateAsync("two", target: "beta:model");
            await alpha.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
            await beta.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));

            var queuedAlpha = client.GenerateAsync("three", target: "alpha:model");
            Assert.Equal(1, alpha.SendCalls);
            Assert.Equal(1, beta.SendCalls);

            alpha.Release.TrySetResult();
            beta.Release.TrySetResult();
            await Task.WhenAll(firstAlpha, betaRequest);
            await alpha.SecondEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
            await queuedAlpha;

            Assert.Equal(2, alpha.SendCalls);
            Assert.Equal(1, beta.SendCalls);
            var observed = events.Events
                .OfType<RateLimitObserved>()
                .OrderBy(static item => item.ProviderId, StringComparer.Ordinal)
                .ToArray();
            Assert.Equal(2, observed.Length);
            Assert.Equal("alpha", observed[0].ProviderId);
            Assert.Equal("beta", observed[1].ProviderId);
            Assert.All(observed, item =>
            {
                Assert.Equal(1L, item.RequestsRemaining);
                Assert.Equal(1d, item.ResetsInS);
            });
        }
        finally
        {
            alpha.Release.TrySetResult();
            beta.Release.TrySetResult();
        }
    }

    [Fact]
    public async Task Inactive_injected_limiter_suppresses_active_settings_fallback()
    {
        var handler = new BlockingHandler();
        var inactive = new RateLimiter(new RateLimits(respectHeaders: false));
        await using var client = CreateClient(
            [Settings("alpha", handler, new RateLimits(maxConcurrent: 1))],
            limiters: new Dictionary<string, RateLimiter> { ["ALPHA"] = inactive });

        var first = client.GenerateAsync("one", target: "alpha:model");
        var second = client.GenerateAsync("two", target: "alpha:model");
        await handler.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        await handler.SecondEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.Equal(2, handler.SendCalls);

        handler.Release.TrySetResult();
        await Task.WhenAll(first, second);
    }

    [Fact]
    public async Task Governed_raw_transport_retains_the_owned_tls_configuration()
    {
        await using var fixture = LoopbackConnectionFixture.Start();
        var settings = ProviderSettings.Of(
            "openai-compat",
            fixture.OriginUri.ToString(),
            "key",
            limits: new RateLimits(maxConcurrent: 1),
            verify: TlsVerification.FromPemBundle(fixture.CertificatePemPath));
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());

        await Assert.ThrowsAsync<AllTargetsFailedException>(() =>
            client.GenerateAsync("governed", target: "openai-compat:model"));

        Assert.Equal(1, fixture.OriginRequests);
    }

    [Fact]
    public async Task Governed_response_content_releases_the_permit_only_after_original_content_cleanup()
    {
        var firstContent = new TrackingContent();
        var handler = new OrderedContentHandler(firstContent);
        var client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))]);
        try
        {
            var first = client.GenerateAsync("first", target: "alpha:model");
            await firstContent.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            var second = client.GenerateAsync("second", target: "alpha:model");
            Assert.Equal(1, handler.SendCalls);

            firstContent.Release.TrySetResult();
            await first;
            Assert.True(firstContent.Disposed);
            await handler.SecondSend.Task.WaitAsync(TimeSpan.FromSeconds(1));
            await second;
            Assert.Equal(2, handler.SendCalls);
        }
        finally
        {
            firstContent.Release.TrySetResult();
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Send_failure_preserves_the_native_fault_and_releases_the_governed_slot()
    {
        var sentinel = new IOException("send failed");
        var handler = new FailingThenSuccessHandler(sentinel);
        await using var client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))]);

        var failure = await Assert.ThrowsAsync<IOException>(() => client.GenerateAsync("first", target: "alpha:model"));
        Assert.Same(sentinel, failure);

        var result = await client.GenerateAsync("second", target: "alpha:model");
        Assert.Equal("ok", result.Text);
        Assert.Equal(2, handler.SendCalls);
    }

    [Fact]
    public async Task Non_success_response_headers_are_observed_and_error_content_cleanup_releases_the_permit()
    {
        var content = new TrackingContent("""{"error":{"message":"busy"}}""");
        content.Release.TrySetResult();
        var handler = new ErrorThenSuccessHandler(content);
        var events = new Collector();
        await using var client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))], events);

        var route = new Route(
            ["alpha:model"],
            new Retry(MaxAttempts: 1, BackoffBaseS: 0, BackoffMaxS: 0),
            healthGate: false);
        var failure = await Assert.ThrowsAsync<AllTargetsFailedException>(() =>
            client.GenerateAsync(
                "first",
                route: route));
        var attempt = Assert.Single(failure.Attempts);
        var provider = Assert.IsType<ProviderUnavailableException>(attempt.Error);
        Assert.Equal(503, provider.HttpStatus);
        Assert.True(content.Disposed);
        Assert.Equal(1L, Assert.Single(events.Events.OfType<RateLimitObserved>()).RequestsRemaining);

        Assert.Equal("ok", (await client.GenerateAsync("second", route: route)).Text);
        Assert.Equal(2, handler.SendCalls);
    }

    [Fact]
    public async Task Observer_failures_are_isolated_and_do_not_prevent_governed_reuse()
    {
        var source = new InvalidOperationException("observe callback");
        var content = new TrackingContent();
        content.Release.TrySetResult();
        var handler = new ErrorThenSuccessHandler(content, HttpStatusCode.OK);
        var observer = new ThrowOnRateLimitObserved(source);
        await using var client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))], observer);

        Assert.Equal("ok", (await client.GenerateAsync("first", target: "alpha:model")).Text);
        Assert.True(content.Disposed);

        Assert.Equal("ok", (await client.GenerateAsync("second", target: "alpha:model")).Text);
        Assert.Equal(2, handler.SendCalls);
    }

    [Fact]
    public async Task Injected_limiter_callback_failure_preserves_its_exact_source_and_releases_the_permit()
    {
        var source = new InvalidOperationException("injected limiter callback");
        var content = new TrackingContent();
        content.Release.TrySetResult();
        var handler = new ErrorThenSuccessHandler(content, HttpStatusCode.OK);
        var limiter = new RateLimiter(
            new RateLimits(maxConcurrent: 1, respectHeaders: true),
            HeaderDialect,
            "alpha",
            telemetryEvent =>
            {
                if (telemetryEvent is RateLimitObserved) throw source;
            });
        await using var client = CreateClient(
            [Settings("alpha", handler, new RateLimits(maxConcurrent: 1))],
            limiters: new Dictionary<string, RateLimiter> { ["alpha"] = limiter });

        var failure = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            client.GenerateAsync("first", target: "alpha:model"));
        Assert.Same(source, failure);
        Assert.True(content.Disposed);

        Assert.Equal("ok", (await client.GenerateAsync("second", target: "alpha:model").WaitAsync(TimeSpan.FromSeconds(5))).Text);
        Assert.Equal(2, handler.SendCalls);
    }

    [Fact]
    public async Task Wrapped_content_forwards_the_actual_cancellable_read_token_and_releases_after_read_cancellation()
    {
        var content = new CancellableReadContent();
        var handler = new SingleContentHandler(content);
        var client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))]);
        using var caller = new CancellationTokenSource();
        try
        {
            var pending = client.GenerateAsync("blocked", target: "alpha:model", cancellationToken: caller.Token);
            await content.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            caller.Cancel();

            var cancellation = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending.WaitAsync(TimeSpan.FromSeconds(1)));
            Assert.Equal(caller.Token, cancellation.CancellationToken);
            await content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.True(content.ReadToken.CanBeCanceled);
            Assert.True(content.Disposed);
        }
        finally
        {
            content.Release.TrySetResult();
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Early_public_stream_close_waits_for_held_sse_body_cleanup_before_releasing_the_governed_slot()
    {
        var content = new SseGateContent();
        var handler = new SingleContentThenSuccessHandler(content);
        var client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))]);
        AsyncStream? stream = null;
        IAsyncEnumerator<StreamEvent>? enumerator = null;
        Task<bool>? pendingRead = null;
        Task? closing = null;
        Task<Generation>? queued = null;
        Exception? primary = null;
        try
        {
            stream = client.StreamAsync("stream", target: "alpha:model");
            enumerator = stream.GetAsyncEnumerator();
            TextDelta? text = null;
            for (var index = 0; index < 4; index++)
            {
                var moved = await enumerator.MoveNextAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(1));
                if (!moved) break;
                if (enumerator.Current is TextDelta delta)
                {
                    text = delta;
                    break;
                }
            }

            Assert.NotNull(text);
            Assert.Equal("chunk", text!.Text);

            pendingRead = enumerator.MoveNextAsync().AsTask();
            await content.SecondReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
            queued = client.GenerateAsync("after", target: "alpha:model");
            Assert.Equal(1, handler.SendCalls);
            closing = stream.DisposeAsync().AsTask();
            await content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.False(closing.IsCompleted);
            Assert.False(queued.IsCompleted);
            Assert.Equal(1, handler.SendCalls);

            content.Release.TrySetResult();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pendingRead.WaitAsync(TimeSpan.FromSeconds(1)));
            await closing.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.True(content.Disposed);

            await handler.SecondSend.Task.WaitAsync(TimeSpan.FromSeconds(1));
            Assert.Equal("ok", (await queued.WaitAsync(TimeSpan.FromSeconds(1))).Text);
            Assert.Equal(2, handler.SendCalls);
        }
        catch (Exception exception)
        {
            primary = exception;
            throw;
        }
        finally
        {
            content.Release.TrySetResult();
            Exception? cleanupFailure = null;
            try
            {
                if (enumerator is not null)
                {
                    await enumerator.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(1));
                }
            }
            catch (Exception exception)
            {
                cleanupFailure = exception;
            }

            try
            {
                if (stream is not null)
                {
                    await stream.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(1));
                }

                if (pendingRead is not null)
                {
                    try
                    {
                        await pendingRead.WaitAsync(TimeSpan.FromSeconds(1));
                    }
                    catch (OperationCanceledException)
                    {
                    }
                }

                if (closing is not null)
                {
                    await closing.WaitAsync(TimeSpan.FromSeconds(1));
                }

                if (queued is not null)
                {
                    await queued.WaitAsync(TimeSpan.FromSeconds(1));
                }
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            try
            {
                await client.DisposeAsync();
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            if (primary is null && cleanupFailure is not null)
            {
                ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
            }
        }
    }

    [Fact]
    public async Task Same_instance_factory_reentry_is_actionable()
    {
        AsyncClient? client = null;
        InvalidOperationException? nestedFailure = null;
        var nested = new ProviderDescriptor(
            "alpha",
            "Alpha",
            (_, _) =>
            {
                nestedFailure = Assert.Throws<InvalidOperationException>(() =>
                    client!.ModelsAsync("alpha").GetAwaiter().GetResult());
                Assert.Contains("factory", nestedFailure.Message, StringComparison.OrdinalIgnoreCase);
                return ValueTask.FromException<IAsyncDisposable>(nestedFailure);
            },
            defaultBaseUrl: "https://fixture.invalid/v1",
            requiresBaseUrl: true,
            rateLimitHeaders: HeaderDialect);
        client = new AsyncClient([SettingsFor("alpha", new BlockingHandler())], new ProviderRegistry([nested]));
        try
        {
            var outer = await Assert.ThrowsAsync<InvalidOperationException>(() => client.ModelsAsync("alpha"));
            Assert.Same(nestedFailure, outer);
        }
        finally
        {
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Factory_chain_rejects_an_active_ancestor_but_allows_a_distinct_instance()
    {
        var alphaHandler = new ModelsHandler();
        var betaHandler = new ModelsHandler();
        AsyncClient? client = null;
        InvalidOperationException? ancestor = null;
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat").Factory;
        ProviderDescriptor? first = null;
        var second = new ProviderDescriptor(
            "beta",
            "Beta",
            async (config, token) =>
            {
                ancestor = await Assert.ThrowsAsync<InvalidOperationException>(() => client!.ModelsAsync("alpha"));
                Assert.Contains("factory", ancestor.Message, StringComparison.OrdinalIgnoreCase);
                return await builtin(config, token);
            },
            defaultBaseUrl: "https://fixture.invalid/v1",
            requiresBaseUrl: true,
            rateLimitHeaders: HeaderDialect);
        first = new ProviderDescriptor(
            "alpha",
            "Alpha",
            async (config, token) =>
            {
                var models = await client!.ModelsAsync("beta");
                Assert.NotEmpty(models);
                return await builtin(config, token);
            },
            defaultBaseUrl: "https://fixture.invalid/v1",
            requiresBaseUrl: true,
            rateLimitHeaders: HeaderDialect);
        client = new AsyncClient(
            [SettingsFor("alpha", alphaHandler), SettingsFor("beta", betaHandler)],
            new ProviderRegistry([first, second]));
        try
        {
            Assert.NotEmpty(await client.ModelsAsync("alpha"));
            Assert.NotNull(ancestor);
        }
        finally
        {
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Captured_factory_context_is_inactive_after_the_factory_returns()
    {
        var handler = new ModelsHandler();
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Task<int>? captured = null;
        AsyncClient? client = null;
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat").Factory;
        var descriptor = new ProviderDescriptor(
            "alpha",
            "Alpha",
            async (config, token) =>
            {
                captured = Task.Run(async () =>
                {
                    await release.Task;
                    return (await client!.ModelsAsync("alpha")).Count;
                });
                return await builtin(config, token);
            },
            defaultBaseUrl: "https://fixture.invalid/v1",
            requiresBaseUrl: true,
            rateLimitHeaders: HeaderDialect);
        client = new AsyncClient([SettingsFor("alpha", handler)], new ProviderRegistry([descriptor]));
        Exception? primary = null;
        try
        {
            Assert.NotEmpty(await client.ModelsAsync("alpha"));
            release.TrySetResult();
            Assert.True(await captured!.WaitAsync(TimeSpan.FromSeconds(1)) > 0);
        }
        catch (Exception exception)
        {
            primary = exception;
            throw;
        }
        finally
        {
            release.TrySetResult();
            Exception? cleanupFailure = null;
            try
            {
                if (captured is not null)
                {
                    await captured.WaitAsync(TimeSpan.FromSeconds(1));
                }
            }
            catch (Exception exception)
            {
                cleanupFailure = exception;
            }

            try
            {
                await client.DisposeAsync();
            }
            catch (Exception exception)
            {
                cleanupFailure ??= exception;
            }

            if (primary is null && cleanupFailure is not null)
            {
                ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
            }
        }
    }

    [Fact]
    public async Task Async_client_callback_cannot_dispose_its_own_active_client()
    {
        var handler = new ReusableHandler();
        AsyncClient? client = null;
        Exception? callbackFailure = null;
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestStarted && callbackFailure is null)
            {
                callbackFailure = RecordException(() => client!.DisposeAsync());
            }
        });
        client = CreateClient([Settings("alpha", handler, new RateLimits(maxConcurrent: 1))], observer);
        try
        {
            Assert.Equal("ok", (await client.GenerateAsync("value", target: "alpha:model")).Text);
            Assert.IsType<InvalidOperationException>(callbackFailure);
        }
        finally
        {
            await client.DisposeAsync();
        }
    }

    [Fact]
    public void Sync_client_callback_cannot_dispose_its_own_active_client()
    {
        var handler = new ReusableHandler();
        Client? client = null;
        Exception? callbackFailure = null;
        var observer = new CallbackObserver(item =>
        {
            if (item is RequestStarted && callbackFailure is null)
            {
                callbackFailure = RecordException(() =>
                {
                    client!.Dispose();
                    return ValueTask.CompletedTask;
                });
            }
        });
        client = new Client(
            [Settings("alpha", handler, new RateLimits(maxConcurrent: 1))],
            new ProviderRegistry([Descriptor("openai-compat", ProviderRegistry.CreateDefault().Get("openai-compat").Factory)]),
            observers: [observer]);
        try
        {
            Assert.Equal("ok", client.Generate("value", target: "alpha:model").Text);
            Assert.IsType<InvalidOperationException>(callbackFailure);
        }
        finally
        {
            client.Dispose();
        }
    }

    [Fact]
    public async Task Async_client_rate_limit_callback_cannot_dispose_its_own_active_client()
    {
        var handler = new HeaderSuccessHandler();
        AsyncClient? client = null;
        Exception? callbackFailure = null;
        var observer = new CallbackObserver(item =>
        {
            if (item is RateLimitObserved && callbackFailure is null)
            {
                callbackFailure = RecordException(() => client!.DisposeAsync());
            }
        });
        client = CreateClient([Settings("alpha", handler, new RateLimits(respectHeaders: true))], observer);
        try
        {
            Assert.Equal("ok", (await client.GenerateAsync("value", target: "alpha:model")).Text);
            Assert.IsType<InvalidOperationException>(callbackFailure);
            Assert.True(handler.ContentDisposed);
        }
        finally
        {
            await client.DisposeAsync();
        }
    }

    [Fact]
    public void Sync_client_rate_limit_callback_cannot_dispose_its_own_active_client()
    {
        var handler = new HeaderSuccessHandler();
        Client? client = null;
        Exception? callbackFailure = null;
        var observer = new CallbackObserver(item =>
        {
            if (item is RateLimitObserved && callbackFailure is null)
            {
                callbackFailure = RecordException(() =>
                {
                    client!.Dispose();
                    return ValueTask.CompletedTask;
                });
            }
        });
        client = new Client(
            [Settings("alpha", handler, new RateLimits(respectHeaders: true))],
            new ProviderRegistry([Descriptor("openai-compat", ProviderRegistry.CreateDefault().Get("openai-compat").Factory)]),
            observers: [observer]);
        try
        {
            Assert.Equal("ok", client.Generate("value", target: "alpha:model").Text);
            Assert.IsType<InvalidOperationException>(callbackFailure);
            Assert.True(handler.ContentDisposed);
        }
        finally
        {
            client.Dispose();
        }
    }

    [Fact]
    public async Task Borrowed_pool_owned_raw_transport_rebuilds_after_a_late_discard_and_disposes_once_at_client_close()
    {
        var handler = new ReusableHandler();
        var fixture = new HeldBuiltinFactory(handler, poolOwnsTransport: true);
        var client = fixture.CreateClient();
        using var caller = new CancellationTokenSource();

        try
        {
            var pending = client.GenerateAsync("held", target: "alpha:model", cancellationToken: caller.Token);
            await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
            caller.Cancel();
            fixture.Release.TrySetResult();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending.WaitAsync(TimeSpan.FromSeconds(1)));

            Assert.Equal(0, handler.DisposeCalls);
            Assert.Equal("ok", (await client.GenerateAsync("fresh", target: "alpha:model")).Text);
            Assert.Equal(2, fixture.FactoryCalls);
            Assert.Equal(1, handler.SendCalls);
        }
        finally
        {
            fixture.Release.TrySetResult();
            await client.DisposeAsync();
        }
        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Transferred_custom_raw_transport_refuses_rebuild_after_late_discard()
    {
        var handler = new ReusableHandler();
        var fixture = new HeldBuiltinFactory(handler, poolOwnsTransport: false);
        var client = fixture.CreateClient();
        using var caller = new CancellationTokenSource();

        try
        {
            var pending = client.GenerateAsync("held", target: "alpha:model", cancellationToken: caller.Token);
            await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
            caller.Cancel();
            fixture.Release.TrySetResult();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending.WaitAsync(TimeSpan.FromSeconds(1)));

            var refusal = await Assert.ThrowsAsync<ConfigException>(() => client.GenerateAsync("fresh", target: "alpha:model"));
            Assert.Contains("transport", refusal.Detail ?? refusal.Message, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(1, handler.DisposeCalls);
            Assert.Equal(1, fixture.FactoryCalls);
        }
        finally
        {
            fixture.Release.TrySetResult();
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Governed_content_cleanup_preserves_the_original_failure_attempts_both_cleanups_and_releases_the_permit()
    {
        var original = new InvalidOperationException("original content cleanup");
        var cachedStream = new IOException("cached stream cleanup");
        var content = new CleanupFaultContent(original, cachedStream);
        var handler = new CleanupFaultHandler(content);
        var limiter = new RateLimiter(new RateLimits(maxConcurrent: 1));
        using var governed = new GovernedHttpMessageHandler(handler, limiter, ownsInner: false);
        using var invoker = new HttpMessageInvoker(governed, disposeHandler: false);

        using var firstRequest = new HttpRequestMessage(HttpMethod.Get, "https://fixture.invalid/first");
        var first = await invoker.SendAsync(firstRequest, CancellationToken.None);
        _ = await first.Content.ReadAsStreamAsync();
        var failure = Assert.Throws<InvalidOperationException>(() => first.Dispose());
        Assert.Same(original, failure);
        Assert.Equal(1, content.DisposeCalls);
        Assert.Equal(1, content.Stream.DisposeCalls);

        using var secondRequest = new HttpRequestMessage(HttpMethod.Get, "https://fixture.invalid/second");
        using var second = await invoker.SendAsync(secondRequest, CancellationToken.None);
        Assert.Equal(2, handler.SendCalls);
    }

    private static AsyncClient CreateClient(
        IEnumerable<ProviderSettings> settings,
        IObserver? observer = null,
        IReadOnlyDictionary<string, RateLimiter>? limiters = null)
    {
        var descriptor = Descriptor("openai-compat", ProviderRegistry.CreateDefault().Get("openai-compat").Factory);
        return new AsyncClient(
            settings,
            new ProviderRegistry([descriptor]),
            observers: observer is null ? null : [observer],
            limiters: limiters);
    }

    private static ProviderSettings Settings(string alias, HttpMessageHandler handler, RateLimits? limits) =>
        ProviderSettings.Of(
            "openai-compat",
            "https://fixture.invalid/v1",
            "secret",
            transport: handler,
            alias: alias,
            limits: limits);

    private static ProviderSettings SettingsFor(string providerId, HttpMessageHandler handler) =>
        ProviderSettings.Of(
            providerId,
            "https://fixture.invalid/v1",
            "secret",
            transport: handler,
            alias: providerId);

    private static ProviderDescriptor Descriptor(
        string id,
        Func<ProviderConfig, CancellationToken, ValueTask<IAsyncDisposable>> factory) =>
        new(
            id,
            id,
            factory,
            defaultBaseUrl: "https://fixture.invalid/v1",
            requiresBaseUrl: true,
            rateLimitHeaders: HeaderDialect);

    private static Exception? RecordException(Func<ValueTask> callback)
    {
        try
        {
            callback().GetAwaiter().GetResult();
            return null;
        }
        catch (Exception exception)
        {
            return exception;
        }
    }

    private sealed class Collector : IObserver
    {
        internal ConcurrentQueue<TelemetryEvent> Events { get; } = new();
        public void OnEvent(TelemetryEvent telemetryEvent) => Events.Enqueue(telemetryEvent);
    }

    private sealed class ThrowOnRateLimitObserved(Exception source) : IObserver
    {
        public void OnEvent(TelemetryEvent telemetryEvent)
        {
            if (telemetryEvent is RateLimitObserved) throw source;
        }
    }

    private sealed class CallbackObserver(Action<TelemetryEvent> callback) : IObserver
    {
        public void OnEvent(TelemetryEvent telemetryEvent) => callback(telemetryEvent);
    }

    private sealed class BlockingHandler : HttpMessageHandler
    {
        private int _calls;
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource SecondEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            var call = Interlocked.Increment(ref _calls);
            if (call == 1) Entered.TrySetResult(); else SecondEntered.TrySetResult();
            await Release.Task.WaitAsync(cancellationToken);
            var response = SuccessResponse();
            if (call == 1)
            {
                response.Headers.TryAddWithoutValidation("x-remaining", "1");
                response.Headers.TryAddWithoutValidation("x-reset", "1s");
                response.Content.Headers.TryAddWithoutValidation("x-limit", "1");
            }
            return response;
        }
    }

    private sealed class RedirectThenSuccessHandler : HttpMessageHandler
    {
        private int _calls;
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Interlocked.Increment(ref _calls) == 1)
            {
                var redirect = new HttpResponseMessage(HttpStatusCode.TemporaryRedirect);
                redirect.Headers.Location = new Uri("/v1/chat/completions", UriKind.Relative);
                redirect.Headers.TryAddWithoutValidation("x-remaining", "1");
                redirect.Headers.TryAddWithoutValidation("x-reset", "1s");
                return Task.FromResult(redirect);
            }

            var success = SuccessResponse();
            success.Headers.TryAddWithoutValidation("x-remaining", "1");
            success.Headers.TryAddWithoutValidation("x-reset", "1s");
            return Task.FromResult(success);
        }
    }

    private sealed class OrderedContentHandler(TrackingContent first) : HttpMessageHandler
    {
        private int _calls;
        internal TaskCompletionSource SecondSend { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var call = Interlocked.Increment(ref _calls);
            if (call == 1)
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = first });
            }

            SecondSend.TrySetResult();
            return Task.FromResult(SuccessResponse());
        }
    }

    private sealed class FailingThenSuccessHandler(IOException failure) : HttpMessageHandler
    {
        private int _calls;
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Interlocked.Increment(ref _calls) == 1) return Task.FromException<HttpResponseMessage>(failure);
            return Task.FromResult(SuccessResponse());
        }
    }

    private sealed class ErrorThenSuccessHandler : HttpMessageHandler
    {
        private readonly TrackingContent _first;
        private readonly HttpStatusCode _firstStatus;
        private int _calls;

        internal ErrorThenSuccessHandler(TrackingContent first, HttpStatusCode firstStatus = HttpStatusCode.ServiceUnavailable)
        {
            _first = first;
            _firstStatus = firstStatus;
        }

        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Interlocked.Increment(ref _calls) == 1)
            {
                var response = new HttpResponseMessage(_firstStatus) { Content = _first };
                response.Headers.TryAddWithoutValidation("x-remaining", "1");
                response.Headers.TryAddWithoutValidation("x-reset", "1s");
                response.Content.Headers.TryAddWithoutValidation("x-limit", "1");
                return Task.FromResult(response);
            }

            return Task.FromResult(SuccessResponse());
        }
    }

    private sealed class SingleContentHandler(TrackingContent content) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
        }
    }

    private sealed class SingleContentThenSuccessHandler(TrackingContent content) : HttpMessageHandler
    {
        private int _calls;
        internal TaskCompletionSource SecondSend { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Interlocked.Increment(ref _calls) == 1)
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
            }

            SecondSend.TrySetResult();
            return Task.FromResult(SuccessResponse());
        }
    }

    private class TrackingContent : HttpContent
    {
        private readonly byte[] _bytes;
        internal TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool Disposed { get; private set; }

        internal TrackingContent(string? body = null)
        {
            _bytes = Encoding.UTF8.GetBytes(body ?? """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""");
        }

        protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context)
        {
            ReadStarted.TrySetResult();
            await Release.Task;
            await stream.WriteAsync(_bytes);
        }

        protected override bool TryComputeLength(out long length)
        {
            length = _bytes.Length;
            return true;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Disposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class CancellableReadContent : TrackingContent
    {
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal CancellationToken ReadToken { get; private set; }

        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken)
        {
            ReadToken = cancellationToken;
            return Task.FromResult<Stream>(new CancellableReadStream(ReadStarted, CancellationObserved, cancellationToken));
        }
    }

    private sealed class CancellableReadStream(
        TaskCompletionSource started,
        TaskCompletionSource cancellationObserved,
        CancellationToken contentToken) : Stream
    {
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            started.TrySetResult();
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(contentToken, cancellationToken);
            try
            {
                await Task.Delay(Timeout.InfiniteTimeSpan, linked.Token);
                return 0;
            }
            catch (OperationCanceledException)
            {
                cancellationObserved.TrySetResult();
                throw;
            }
        }
    }

    private sealed class SseGateContent : TrackingContent
    {
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource SecondReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        internal SseGateContent()
        {
            Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/event-stream");
        }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }

        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) =>
            Task.FromResult<Stream>(new SseGateStream(
                ReadStarted,
                SecondReadStarted,
                CancellationObserved,
                Release,
                cancellationToken));
    }

    private sealed class SseGateStream(
        TaskCompletionSource firstReadStarted,
        TaskCompletionSource secondReadStarted,
        TaskCompletionSource cancellationObserved,
        TaskCompletionSource release,
        CancellationToken contentToken) : Stream
    {
        private readonly byte[] _first = Encoding.UTF8.GetBytes(
            """data: {"choices":[{"delta":{"content":"chunk"}}]}""" + "\n\n");
        private int _reads;
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (Interlocked.Increment(ref _reads) == 1)
            {
                firstReadStarted.TrySetResult();
                _first.CopyTo(buffer);
                return _first.Length;
            }

            secondReadStarted.TrySetResult();
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(contentToken, cancellationToken);
            try
            {
                await Task.Delay(Timeout.InfiniteTimeSpan, linked.Token);
                return 0;
            }
            catch (OperationCanceledException)
            {
                cancellationObserved.TrySetResult();
                await release.Task;
                throw;
            }
        }
    }

    private sealed class HeldBuiltinFactory(ReusableHandler handler, bool poolOwnsTransport)
    {
        private readonly ProviderDescriptor _builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int FactoryCalls;

        internal AsyncClient CreateClient()
        {
            var descriptor = new ProviderDescriptor(
                _builtin.Id,
                _builtin.DisplayName,
                BuildAsync,
                _builtin.Aliases,
                _builtin.Setup,
                _builtin.DefaultBaseUrl,
                _builtin.RequiresBaseUrl,
                _builtin.StructuredOutputProfiles,
                _builtin.MaxRepairAttempts,
                _builtin.Locality,
                _builtin.DefaultCapabilities,
                _builtin.StaticCapabilities,
                _builtin.Operations,
                _builtin.StaticEmbeddingCapabilities,
                _builtin.StaticRerankCapabilities,
                _builtin.TokenCalibration,
                HeaderDialect)
            {
                PoolOwnsConfiguredTransport = poolOwnsTransport,
            };
            return new AsyncClient(
                [Settings("alpha", handler, new RateLimits(maxConcurrent: 1))],
                new ProviderRegistry([descriptor]));
        }

        private async ValueTask<IAsyncDisposable> BuildAsync(ProviderConfig config, CancellationToken cancellationToken)
        {
            var adapter = await _builtin.Factory(config, cancellationToken);
            if (Interlocked.Increment(ref FactoryCalls) == 1)
            {
                Entered.TrySetResult();
                await Release.Task;
            }

            return adapter;
        }
    }

    private sealed class ReusableHandler : HttpMessageHandler
    {
        private int _sends;
        private int _disposes;
        internal int SendCalls => Volatile.Read(ref _sends);
        internal int DisposeCalls => Volatile.Read(ref _disposes);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Interlocked.Increment(ref _sends);
            return Task.FromResult(SuccessResponse());
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) Interlocked.Increment(ref _disposes);
            base.Dispose(disposing);
        }
    }

    private sealed class HeaderSuccessHandler : HttpMessageHandler
    {
        private TrackingContent? _content;
        internal bool ContentDisposed => _content?.Disposed == true;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            _content = new TrackingContent();
            _content.Release.TrySetResult();
            var response = new HttpResponseMessage(HttpStatusCode.OK) { Content = _content };
            response.Headers.TryAddWithoutValidation("x-remaining", "0");
            response.Headers.TryAddWithoutValidation("x-reset", "1s");
            response.Content.Headers.TryAddWithoutValidation("x-limit", "1");
            return Task.FromResult(response);
        }
    }

    private sealed class ModelsHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (request.Method == HttpMethod.Get)
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("""{"data":[{"id":"fixture-model"}]}""", Encoding.UTF8, "application/json"),
                });
            }

            return Task.FromResult(SuccessResponse());
        }
    }

    private sealed class CleanupFaultHandler(CleanupFaultContent first) : HttpMessageHandler
    {
        private int _calls;
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return Task.FromResult(Interlocked.Increment(ref _calls) == 1
                ? new HttpResponseMessage(HttpStatusCode.OK) { Content = first }
                : SuccessResponse());
        }
    }

    private sealed class CleanupFaultContent(Exception original, Exception cachedStreamFailure) : HttpContent
    {
        internal CleanupFaultStream Stream { get; } = new(cachedStreamFailure);
        internal int DisposeCalls { get; private set; }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return true;
        }

        protected override Task<Stream> CreateContentReadStreamAsync() => Task.FromResult<Stream>(Stream);

        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return Task.FromResult<Stream>(Stream);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                DisposeCalls++;
                throw original;
            }

            base.Dispose(disposing);
        }
    }

    private sealed class CleanupFaultStream(Exception failure) : Stream
    {
        internal int DisposeCalls { get; private set; }
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => 0;
        public override long Position { get => 0; set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
        public override int Read(byte[] buffer, int offset, int count) => 0;
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) => ValueTask.FromResult(0);
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                DisposeCalls++;
                throw failure;
            }

            base.Dispose(disposing);
        }
    }

    private static HttpResponseMessage SuccessResponse() => new(HttpStatusCode.OK)
    {
        Content = new StringContent(
            """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""",
            Encoding.UTF8,
            "application/json"),
    };
}
