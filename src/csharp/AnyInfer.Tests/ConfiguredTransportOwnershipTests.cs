using System.Net;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Configured OpenAI-compatible transport ownership and late-factory controls.</summary>
public sealed class ConfiguredTransportOwnershipTests
{
    [Fact]
    public void Default_openai_compatible_descriptor_opts_into_pool_owned_configured_transports()
    {
        Assert.True(ProviderRegistry.CreateDefault().Get("openai-compat").PoolOwnsConfiguredTransport);
    }

    [Fact]
    public async Task Caller_cancellation_discards_a_held_openai_adapter_without_disposing_its_configured_handler()
    {
        var handler = new TrackingHandler();
        var fixture = new HeldOpenAiFactory(handler, poolOwnsTransport: true);
        var client = fixture.CreateClient();
        using var caller = new CancellationTokenSource();
        try
        {
            var pending = client.StreamAsync("held", target: "openai-compat:model", cancellationToken: caller.Token).CollectAsync(caller.Token);
            await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            caller.Cancel();
            fixture.Release.TrySetResult();

            var cancelled = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(caller.Token, cancelled.CancellationToken);
            Assert.Equal(1, fixture.First!.DisposeCalls);
            Assert.Equal(0, fixture.First.GenerateCalls);
            Assert.Equal(0, handler.SendCalls);
            Assert.Equal(0, handler.DisposeCalls);

            Assert.Equal("ok", (await client.GenerateAsync("fresh", target: "openai-compat:model")).Text);
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
    public async Task Direct_close_discards_a_held_openai_adapter_without_disposing_its_configured_handler()
    {
        var handler = new TrackingHandler();
        var fixture = new HeldOpenAiFactory(handler, poolOwnsTransport: true);
        var client = fixture.CreateClient();
        try
        {
            var stream = client.StreamAsync("held", target: "openai-compat:model");
            var pending = stream.CollectAsync();
            await fixture.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var closing = stream.DisposeAsync().AsTask();
            Assert.False(closing.IsCompleted);
            fixture.Release.TrySetResult();

            await closing.WaitAsync(TimeSpan.FromSeconds(5));
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            Assert.Equal(1, fixture.First!.DisposeCalls);
            Assert.Equal(0, fixture.First.GenerateCalls);
            Assert.Equal(0, handler.SendCalls);
            Assert.Equal(0, handler.DisposeCalls);
            Assert.Equal("ok", (await client.GenerateAsync("fresh", target: "openai-compat:model")).Text);
            Assert.Equal(2, fixture.FactoryCalls);
        }
        finally
        {
            fixture.Release.TrySetResult();
            await client.DisposeAsync();
        }

        Assert.Equal(1, handler.DisposeCalls);
    }

    [Fact]
    public async Task Pool_disposes_opted_in_configured_handlers_for_unused_and_factory_failed_instances()
    {
        var unusedHandler = new TrackingHandler();
        await using (var unused = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: unusedHandler)],
            new ProviderRegistry([CooperativeDescriptor(static (config, token) => ProviderRegistry.CreateDefault().Get("openai-compat").Factory(config, token), true)])))
        {
            Assert.Equal(0, unusedHandler.SendCalls);
        }
        Assert.Equal(1, unusedHandler.DisposeCalls);

        var failedHandler = new TrackingHandler();
        var sentinel = new InvalidOperationException("factory failure");
        var failing = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: failedHandler)],
            new ProviderRegistry([CooperativeDescriptor((_, _) => ValueTask.FromException<IProviderAdapter>(sentinel), true)]), route: new Route(["openai-compat:model"]));
        try
        {
            await Assert.ThrowsAnyAsync<Exception>(() => failing.GenerateAsync("fail", target: "openai-compat:model"));
        }
        finally
        {
            await failing.DisposeAsync();
        }
        Assert.Equal(1, failedHandler.DisposeCalls);
    }

    [Fact]
    public async Task Pool_continues_configured_handler_cleanup_after_one_handler_disposal_fails()
    {
        var sentinel = new InvalidOperationException("handler disposal failure");
        var failing = new TrackingHandler(sentinel);
        var other = new TrackingHandler();
        var descriptor = CooperativeDescriptor((_, _) => ValueTask.FromException<IProviderAdapter>(new InvalidOperationException("unused")), true);
        var client = new AsyncClient(
            [
                ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: failing, alias: "first"),
                ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: other, alias: "second"),
            ],
            new ProviderRegistry([descriptor]));

        var actual = await Assert.ThrowsAnyAsync<Exception>(() => client.DisposeAsync().AsTask());
        Assert.Same(sentinel, actual);
        Assert.Equal(1, failing.DisposeCalls);
        Assert.Equal(1, other.DisposeCalls);
    }

    [Fact]
    public async Task Non_opted_in_factory_retains_adapter_transfer_ownership_of_configured_handler()
    {
        var handler = new TrackingHandler();
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        var descriptor = CooperativeDescriptor(builtin.Factory, poolOwnsTransport: false);
        var client = new AsyncClient(
            [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: handler)],
            new ProviderRegistry([descriptor]),
            route: new Route(["openai-compat:model"]));
        try
        {
            Assert.Equal("ok", (await client.GenerateAsync("owned", target: "openai-compat:model")).Text);
            Assert.Equal(0, handler.DisposeCalls);
        }
        finally
        {
            await client.DisposeAsync();
        }

        Assert.Equal(1, handler.DisposeCalls);
    }

    private static ProviderDescriptor CooperativeDescriptor(Func<ProviderConfig, CancellationToken, ValueTask<IProviderAdapter>> factory, bool poolOwnsTransport)
    {
        var builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        return new ProviderDescriptor(
            builtin.Id,
            builtin.DisplayName,
            factory,
            builtin.Aliases,
            builtin.Setup,
            builtin.DefaultBaseUrl,
            builtin.RequiresBaseUrl)
        {
            PoolOwnsConfiguredTransport = poolOwnsTransport,
        };
    }

    private sealed class HeldOpenAiFactory(TrackingHandler handler, bool poolOwnsTransport)
    {
        private readonly ProviderDescriptor _builtin = ProviderRegistry.CreateDefault().Get("openai-compat");
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int FactoryCalls;
        internal TrackingAdapter? First { get; private set; }

        internal AsyncClient CreateClient()
        {
            var descriptor = CooperativeDescriptor(BuildAsync, poolOwnsTransport);
            return new AsyncClient(
                [ProviderSettings.Of("openai-compat", "https://fixture.invalid/v1", "secret", transport: handler)],
                new ProviderRegistry([descriptor]),
                route: new Route(["openai-compat:model"]));
        }

        private async ValueTask<IProviderAdapter> BuildAsync(ProviderConfig config, CancellationToken cancellationToken)
        {
            var adapter = new TrackingAdapter(await _builtin.Factory(config, cancellationToken));
            if (Interlocked.Increment(ref FactoryCalls) == 1)
            {
                First = adapter;
                Entered.TrySetResult();
                await Release.Task;
            }
            return adapter;
        }
    }

    private sealed class TrackingAdapter(IProviderAdapter inner) : IProviderAdapter
    {
        internal int GenerateCalls { get; private set; }
        internal int DisposeCalls { get; private set; }
        public IAsyncEnumerable<AdapterEvent> GenerateAsync(WireRequest request, CancellationToken cancellationToken = default)
        {
            GenerateCalls++;
            return inner.GenerateAsync(request, cancellationToken);
        }
        public async ValueTask DisposeAsync()
        {
            DisposeCalls++;
            await inner.DisposeAsync();
        }
    }

    private sealed class TrackingHandler(Exception? disposalFailure = null) : HttpMessageHandler
    {
        internal int SendCalls { get; private set; }
        internal int DisposeCalls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            SendCalls++;
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/v1/chat/completions", request.RequestUri!.AbsolutePath);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""", Encoding.UTF8, "application/json"),
            });
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                DisposeCalls++;
                if (disposalFailure is not null) throw disposalFailure;
            }
            base.Dispose(disposing);
        }
    }
}
