using System.Text.Json;
using System.Net;
using System.Text;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public builtin paths retain independently observable redirect controls.</summary>
public sealed class RedirectAdapterTests
{
    [Fact]
    public void Shared_stimulus_is_input_only_and_copy_linked_for_native_controls()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "redirects", "provider_redirects.json");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var cases = document.RootElement.GetProperty("cases").EnumerateArray().ToArray();
        Assert.Equal(8, cases.Length);
        Assert.All(cases, item =>
        {
            Assert.True(item.TryGetProperty("request", out _));
            Assert.True(item.TryGetProperty("responses", out _));
            Assert.False(item.TryGetProperty("expected", out _));
        });
    }

    [Fact]
    public async Task Shared_stimulus_drives_a_real_owned_handler_redirect_sequence()
    {
        var stimulus = LoadStimulus("same-origin");
        await using var fixture = LoopbackRedirectFixture.Start(
            stimulus.Responses.Select(response => new LoopbackRedirectResponse(
                response.Status,
                response.Status == 200 ? "{}" : "",
                response.Location)).ToArray());
        var settings = ProviderSettings.Of("openai-compat", fixture.OriginUri.ToString(), "key");
        var config = new ProviderConfig(settings, "openai-compat", "key");
        using var client = new HttpClient(ConnectionHandlerFactory.CreateOwned(config, CancellationToken.None), true);
        var sender = new ProviderHttpRedirects(client);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        using var exchange = await sender.SendAsync(
            new Uri(fixture.OriginUri, "v1/chat/completions"), HttpMethod.Post,
            context => CreateRequest(context, includeHeaders: true), "generate", budget.Token);

        Assert.Equal(2, fixture.Requests.Count);
        Assert.All(fixture.Requests, request => Assert.Equal("{}", System.Text.Encoding.UTF8.GetString(request.Body)));
        Assert.NotNull(exchange.Response.Content);
    }

    [Fact]
    public async Task Every_shared_stimulus_drives_an_independent_native_transport_sequence()
    {
        foreach (var stimulus in LoadAllStimuli())
        {
            var handler = new StimulusHandler(stimulus.Responses);
            using var client = new HttpClient(handler, true);
            var sender = new ProviderHttpRedirects(client);
            using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            if (stimulus.Id == "unsupported-userinfo")
            {
                await Assert.ThrowsAsync<HttpRequestException>(() => sender.SendAsync(
                    new Uri(new Uri("https://first.example"), stimulus.Path),
                    new HttpMethod(stimulus.Method),
                    context => CreateFixtureRequest(context, stimulus), "generate", budget.Token).AsTask());
            }
            else
            {
                using var exchange = await sender.SendAsync(
                    new Uri(new Uri("https://first.example"), stimulus.Path),
                    new HttpMethod(stimulus.Method),
                    context => CreateFixtureRequest(context, stimulus), "generate", budget.Token);
                Assert.Equal(stimulus.Id == "terminal-missing-location" ? 302 : 200, (int)exchange.Response.StatusCode);
            }

            var requests = handler.Requests.ToArray();
            Assert.Equal(stimulus.Id is "unsupported-userinfo" or "terminal-missing-location" ? 1 : stimulus.Responses.Count, requests.Length);
            AssertFixtureWireFacts(stimulus, requests);
        }
    }

    [Fact]
    public async Task Public_openai_generation_discovery_and_health_use_owned_redirect_wiring()
    {
        await using var generationFixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "/chat/completions"),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}"""));
        await using (var client = Client("openai-compat", generationFixture.OriginUri))
        {
            using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            var generation = await client.GenerateAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15));
            Assert.Equal("ok", generation.Text);
            Assert.Equal(2, generationFixture.Requests.Count);
            Assert.All(generationFixture.Requests, request => Assert.Equal("POST", request.RequestLine[..4]));
            Assert.All(generationFixture.Requests, request => Assert.NotEmpty(request.Body));
        }

        await using var discoveryFixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(302, "", "/models"),
            new LoopbackRedirectResponse(200, """{"data":[]}"""));
        await using (var client = Client("openai-compat", discoveryFixture.OriginUri))
        {
            using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            Assert.Empty(await client.ModelsAsync("openai-compat", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15)));
            Assert.True((await client.HealthAsync("openai-compat", budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Ok);
            Assert.True(discoveryFixture.Requests.Count >= 2);
        }
    }

    [Fact]
    public async Task Public_openai_cross_origin_redirect_derives_host_and_omits_configured_names()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "redirect-pending"),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}"""));
        var changedOrigin = new UriBuilder(fixture.OriginUri) { Host = "localhost", Path = "/chat/completions" }.Uri;
        fixture.ReplaceFirstLocation(changedOrigin.ToString());
        var settings = ProviderSettings.Of("openai-compat", fixture.OriginUri.ToString(), "key",
            headers: new Dictionary<string, string> { ["Accept"] = "application/configured", ["Content-Type"] = "application/configured-json", ["X-Configured"] = "present" });
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        Assert.Equal("ok", (await client.GenerateAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Text);
        var requests = fixture.Requests.ToArray();
        Assert.Equal("application/configured", requests[0].Headers["Accept"]);
        Assert.Equal("application/configured-json", requests[0].Headers["Content-Type"]);
        Assert.Equal("present", requests[0].Headers["X-Configured"]);
        Assert.StartsWith("Bearer ", requests[0].Headers["Authorization"], StringComparison.Ordinal);
        Assert.Equal(changedOrigin.Authority, requests[1].Headers["Host"]);
        Assert.DoesNotContain("Authorization", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("Accept", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("Content-Type", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("X-Configured", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.NotEmpty(requests[1].Body);
        Assert.Equal(requests[1].Body.Length.ToString(System.Globalization.CultureInfo.InvariantCulture), requests[1].Headers["Content-Length"]);
        Assert.DoesNotContain("Transfer-Encoding", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Public_stream_is_inert_until_advanced_and_redirects_through_the_owned_handler()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "/chat/completions"),
            new LoopbackRedirectResponse(200, "data: {\"choices\":[{\"delta\":{\"content\":\"chunk\"}}]}\n\ndata: [DONE]\n\n", ContentType: "text/event-stream"));
        await using var client = Client("openai-compat", fixture.OriginUri);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        await using var stream = client.StreamAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token);
        Assert.Empty(fixture.Requests);
        var generation = await stream.CollectAsync(budget.Token).WaitAsync(TimeSpan.FromSeconds(15));

        Assert.Equal("chunk", generation.Text);
        Assert.Equal(2, fixture.Requests.Count);
    }

    [Theory]
    [InlineData("tei", "[[0.5]]")]
    [InlineData("voyage", """{"data":[{"embedding":[0.5],"index":0}]}""")]
    [InlineData("jina", """{"data":[{"embedding":[0.5],"index":0}]}""")]
    public async Task Public_retrieval_adapters_follow_redirects_with_fresh_owned_requests(string provider, string body)
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "redirect-pending"),
            new LoopbackRedirectResponse(200, body));
        var changedOrigin = new UriBuilder(fixture.OriginUri) { Host = "localhost", Path = "/redirected" }.Uri;
        fixture.ReplaceFirstLocation(changedOrigin.ToString());
        var settings = ProviderSettings.Of(provider, fixture.OriginUri.ToString(), "key",
            headers: new Dictionary<string, string> { ["Accept"] = "application/configured", ["Content-Type"] = "application/configured-json", ["X-Configured"] = "present" });
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        var result = await client.EmbedAsync("input", target: $"{provider}:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15));

        Assert.Single(result.Vectors);
        Assert.Equal(2, fixture.Requests.Count);
        var requests = fixture.Requests.ToArray();
        Assert.Equal("application/configured", requests[0].Headers["Accept"]);
        Assert.Equal("application/configured-json", requests[0].Headers["Content-Type"]);
        Assert.Equal("present", requests[0].Headers["X-Configured"]);
        Assert.NotEmpty(requests[0].Headers["Authorization"]);
        Assert.All(requests, request => Assert.Equal("POST", request.RequestLine[..4]));
        Assert.All(requests, request => Assert.NotEmpty(request.Body));
        Assert.Equal(changedOrigin.Authority, requests[1].Headers["Host"]);
        Assert.DoesNotContain("Authorization", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("Accept", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("Content-Type", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("X-Configured", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain("Transfer-Encoding", requests[1].Headers.Keys, StringComparer.OrdinalIgnoreCase);
        Assert.Equal(requests[1].Body.Length.ToString(System.Globalization.CultureInfo.InvariantCulture), requests[1].Headers["Content-Length"]);
    }

    [Theory]
    [InlineData("openai-compat", "generate", """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""")]
    [InlineData("tei", "embed", "[[0.5]]")]
    [InlineData("voyage", "embed", """{"data":[{"embedding":[0.5],"index":0}]}""")]
    [InlineData("jina", "embed", """{"data":[{"embedding":[0.5],"index":0}]}""")]
    public async Task Public_final_factories_preserve_configured_headers_on_same_origin_without_sdk_fallback(string provider, string operation, string body)
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "/same"),
            new LoopbackRedirectResponse(200, body));
        var settings = ProviderSettings.Of(provider, fixture.OriginUri.ToString(), "key",
            headers: new Dictionary<string, string> { ["Accept"] = "application/configured", ["Content-Type"] = "application/configured-json", ["X-Configured"] = "present" });
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        if (operation == "generate")
            Assert.Equal("ok", (await client.GenerateAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Text);
        else
            Assert.Single((await client.EmbedAsync("input", target: $"{provider}:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Vectors);

        var requests = fixture.Requests.ToArray();
        Assert.Equal(2, requests.Length);
        Assert.All(requests, request =>
        {
            Assert.Equal(fixture.OriginUri.Authority, request.Headers["Host"]);
            Assert.Equal("application/configured", request.Headers["Accept"]);
            Assert.Equal("present", request.Headers["X-Configured"]);
            Assert.DoesNotContain("Transfer-Encoding", request.Headers.Keys, StringComparer.OrdinalIgnoreCase);
            Assert.NotEmpty(request.Body);
        });
    }

    [Theory]
    [InlineData("openai-compat", "generate", """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}""")]
    [InlineData("tei", "embed", "[[0.5]]")]
    [InlineData("voyage", "embed", """{"data":[{"embedding":[0.5],"index":0}]}""")]
    [InlineData("jina", "embed", """{"data":[{"embedding":[0.5],"index":0}]}""")]
    public async Task Public_final_factories_post_to_get_rewrite_drops_body_and_framing(string provider, string operation, string body)
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(303, "", "/rewritten"),
            new LoopbackRedirectResponse(200, body));
        var settings = ProviderSettings.Of(provider, fixture.OriginUri.ToString(), "key",
            headers: new Dictionary<string, string> { ["Host"] = fixture.OriginUri.Authority, ["Accept"] = "application/configured" });
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        if (operation == "generate")
            Assert.Equal("ok", (await client.GenerateAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Text);
        else
            Assert.Single((await client.EmbedAsync("input", target: $"{provider}:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Vectors);

        var requests = fixture.Requests.ToArray();
        Assert.Equal("POST", requests[0].RequestLine[..4]);
        Assert.Equal("GET", requests[1].RequestLine[..3]);
        Assert.Empty(requests[1].Body);
        Assert.True(!requests[1].Headers.TryGetValue("Content-Length", out var contentLength) || contentLength == "0");
        Assert.False(requests[1].Headers.ContainsKey("Transfer-Encoding"));
        Assert.Equal(fixture.OriginUri.Authority, requests[1].Headers["Host"]);
    }

    [Fact]
    public async Task Public_owned_openai_cookie_from_final_response_is_used_by_the_next_operation()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"one"},"finish_reason":"stop"}]}""", SetCookies: ["final=three; Path=/"]),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"two"},"finish_reason":"stop"}]}"""));
        await using var client = Client("openai-compat", fixture.OriginUri);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await client.GenerateAsync("one", target: "openai-compat:model", cancellationToken: budget.Token);
        await client.GenerateAsync("two", target: "openai-compat:model", cancellationToken: budget.Token);

        var requests = fixture.Requests.ToArray();
        Assert.Equal(2, requests.Length);
        Assert.Contains("final=three", requests[1].Headers["Cookie"], StringComparison.Ordinal);
    }

    [Fact]
    public async Task Public_owned_openai_cookie_replaces_expired_and_large_cookie_sets_without_cross_client_leakage()
    {
        var longValue = new string('x', 4097);
        var firstCookies = Enumerable.Range(0, 301).Select(index => $"c{index}=v{index}; Path=/").ToArray();
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"one"},"finish_reason":"stop"}]}""", SetCookies: [.. firstCookies, $"long={longValue}; Path=/", "replace=old; Path=/", "expired=x; Max-Age=0; Path=/"]),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"two"},"finish_reason":"stop"}]}"""),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"other"},"finish_reason":"stop"}]}"""));
        await using var first = Client("openai-compat", fixture.OriginUri);
        await using var second = Client("openai-compat", fixture.OriginUri);
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        await first.GenerateAsync("one", target: "openai-compat:model", cancellationToken: budget.Token);
        await first.GenerateAsync("two", target: "openai-compat:model", cancellationToken: budget.Token);
        await second.GenerateAsync("other", target: "openai-compat:model", cancellationToken: budget.Token);

        var requests = fixture.Requests.ToArray();
        Assert.Contains("c300=v300", requests[1].Headers["Cookie"], StringComparison.Ordinal);
        Assert.Contains($"long={longValue}", requests[1].Headers["Cookie"], StringComparison.Ordinal);
        Assert.DoesNotContain("expired=x", requests[1].Headers["Cookie"], StringComparison.Ordinal);
        Assert.False(requests[2].Headers.ContainsKey("Cookie"));
    }

    [Fact]
    public async Task Public_owned_openai_cookie_recalculation_replaces_initial_literal_on_redirect()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "/next", ["scoped=one; Path=/", "replace=old; Path=/", "replace=new; Path=/"]),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}"""));
        var settings = ProviderSettings.Of("openai-compat", fixture.OriginUri.ToString(), "key",
            headers: new Dictionary<string, string> { ["Cookie"] = "literal=initial" });
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        Assert.Equal("ok", (await client.GenerateAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15))).Text);

        var requests = fixture.Requests.ToArray();
        Assert.Contains("literal=initial", requests[0].Headers["Cookie"], StringComparison.Ordinal);
        Assert.DoesNotContain("literal=initial", requests[1].Headers["Cookie"], StringComparison.Ordinal);
        Assert.Contains("scoped=one", requests[1].Headers["Cookie"], StringComparison.Ordinal);
        Assert.Contains("replace=new", requests[1].Headers["Cookie"], StringComparison.Ordinal);
        Assert.DoesNotContain("replace=old", requests[1].Headers["Cookie"], StringComparison.Ordinal);
    }

    [Fact]
    public async Task Public_owned_http_cookie_scope_sends_only_matching_path_and_nonsecure_domain_values()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "/v1/redirect", [
                "path-ok=one; Path=/v1", "domain-ok=one; Domain=127.0.0.1; Path=/v1", "path-no=two; Path=/other", "secure-no=three; Secure; Path=/",
                "expired=no; Max-Age=0; Path=/", "wrong-domain=no; Domain=invalid.example; Path=/"]),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"one"},"finish_reason":"stop"}]}"""),
            new LoopbackRedirectResponse(200, """{"choices":[{"message":{"content":"two"},"finish_reason":"stop"}]}"""));
        await using var client = Client("openai-compat", new Uri(fixture.OriginUri, "v1/"));
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await client.GenerateAsync("one", target: "openai-compat:model", cancellationToken: budget.Token);
        await client.GenerateAsync("two", target: "openai-compat:model", cancellationToken: budget.Token);

        var requests = fixture.Requests.ToArray();
        Assert.Equal(3, requests.Length);
        foreach (var cookie in new[] { requests[1].Headers["Cookie"], requests[2].Headers["Cookie"] })
        {
            Assert.Contains("path-ok=one", cookie, StringComparison.Ordinal);
            Assert.Contains("domain-ok=one", cookie, StringComparison.Ordinal);
            Assert.DoesNotContain("path-no=two", cookie, StringComparison.Ordinal);
            Assert.DoesNotContain("secure-no=three", cookie, StringComparison.Ordinal);
            Assert.DoesNotContain("expired=no", cookie, StringComparison.Ordinal);
            Assert.DoesNotContain("wrong-domain=no", cookie, StringComparison.Ordinal);
        }
    }

    [Fact]
    public async Task Public_injected_https_cookie_scope_accepts_matching_secure_domain_without_tls_claim()
    {
        var handler = new StimulusHandler([
            new RedirectResponseStimulus(200, null, ["secure-ok=one; Secure; Domain=first.example; Path=/"]),
            new RedirectResponseStimulus(200, null, [])]);
        var settings = ProviderSettings.Of("openai-compat", "https://first.example", "key", transport: handler);
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await client.GenerateAsync("one", target: "openai-compat:model", cancellationToken: budget.Token);
        await client.GenerateAsync("two", target: "openai-compat:model", cancellationToken: budget.Token);
        Assert.Contains("secure-ok=one", handler.Requests.ToArray()[1].Header("Cookie"), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Same_public_client_concurrent_redirect_chains_keep_origin_and_cookie_state_isolated()
    {
        var handler = new ConcurrentCookieRedirectHandler();
        var settings = ProviderSettings.Of("openai-compat", "https://first.example", "key", transport: handler);
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var first = client.GenerateAsync("a", target: "openai-compat:model", cancellationToken: budget.Token);
        var second = client.GenerateAsync("b", target: "openai-compat:model", cancellationToken: budget.Token);
        await handler.BothInitial.Task.WaitAsync(TimeSpan.FromSeconds(15));
        handler.Release.TrySetResult();
        await Task.WhenAll(first, second).WaitAsync(TimeSpan.FromSeconds(15));
        var snapshots = handler.Requests.ToArray();
        Assert.Contains(snapshots, request => request.Uri.Host == "second.example" && !request.Headers.ContainsKey("Authorization"));
        Assert.Contains(snapshots, request => request.Uri.Host == "first.example" && request.Headers.ContainsKey("Authorization"));
        Assert.Contains(snapshots, request => request.Uri.Host == "first.example" && request.Headers.TryGetValue("Cookie", out var cookie) && cookie.Contains("safe=one", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Borrowed_auto_follow_handler_keeps_its_own_cookie_and_hidden_hop_behavior()
    {
        await using var fixture = LoopbackRedirectFixture.Start(
            new LoopbackRedirectResponse(307, "", "/chat/completions", ["caller=owned; Path=/"]),
            new LoopbackRedirectResponse(
                200,
                """{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""",
                Headers: new Dictionary<string, string> { ["x-remaining"] = "1", ["x-reset"] = "1s" }));
        var cookies = new CookieContainer();
        using var handler = new HttpClientHandler
        {
            AllowAutoRedirect = true,
            UseCookies = true,
            CookieContainer = cookies,
        };
        using var recorder = new SendCountingHandler(handler);
        var settings = ProviderSettings.Of(
            "openai-compat", fixture.OriginUri.ToString(), "key",
            transport: recorder, limits: new RateLimits(maxConcurrent: 1));
        await using var client = new AsyncClient([settings], ProviderRegistry.CreateDefault());
        using var budget = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        var generation = await client.GenerateAsync("prompt", target: "openai-compat:model", cancellationToken: budget.Token).WaitAsync(TimeSpan.FromSeconds(15));

        Assert.Equal("ok", generation.Text);
        Assert.True(handler.AllowAutoRedirect);
        Assert.True(handler.UseCookies);
        Assert.Same(cookies, handler.CookieContainer);
        Assert.Equal(1, recorder.SendCount);
        Assert.Equal(2, fixture.Requests.Count);
        Assert.Contains("caller=owned", fixture.Requests.ElementAt(1).Headers["Cookie"], StringComparison.Ordinal);
        // The handler's hidden follow is caller-owned: the SDK observes only its final exchange.
        Assert.Equal(2, fixture.Requests.Count);
    }

    [Fact]
    public async Task Public_stream_early_close_cleans_the_gated_response_and_releases_the_permit()
    {
        var handler = new GatedSseHandler();
        var client = StreamingClient(handler);
        AsyncStream? stream = null;
        IAsyncEnumerator<StreamEvent>? enumerator = null;
        Task<bool>? pending = null;
        try
        {
            stream = client.StreamAsync("prompt", target: "openai-compat:model");
            enumerator = stream.GetAsyncEnumerator();
            TextDelta? text = null;
            while (await enumerator.MoveNextAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(15)))
            {
                if (enumerator.Current is TextDelta delta) { text = delta; break; }
            }
            Assert.Equal("chunk", text!.Text);
            pending = enumerator.MoveNextAsync().AsTask();
            await handler.Content.SecondReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(15));

            var closing = stream.DisposeAsync().AsTask();
            await handler.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(15));
            handler.Content.Release.TrySetResult();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending.WaitAsync(TimeSpan.FromSeconds(15)));
            await closing.WaitAsync(TimeSpan.FromSeconds(15));
            Assert.True(handler.Content.Disposed);
            Assert.Equal("ok", (await client.GenerateAsync("after", target: "openai-compat:model").WaitAsync(TimeSpan.FromSeconds(15))).Text);
            Assert.Equal(2, handler.SendCalls);
        }
        finally
        {
            handler.Content.Release.TrySetResult();
            if (enumerator is not null) await enumerator.DisposeAsync();
            if (stream is not null) await stream.DisposeAsync();
            await client.DisposeAsync();
        }
    }

    [Fact]
    public async Task Public_stream_caller_cancellation_preserves_token_and_releases_the_gated_response()
    {
        var handler = new GatedSseHandler();
        await using var client = StreamingClient(handler);
        using var caller = new CancellationTokenSource();
        await using var stream = client.StreamAsync("prompt", target: "openai-compat:model", cancellationToken: caller.Token);
        await using var enumerator = stream.GetAsyncEnumerator(caller.Token);
        while (await enumerator.MoveNextAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(15)))
        {
            if (enumerator.Current is TextDelta) break;
        }
        var pending = enumerator.MoveNextAsync().AsTask();
        await handler.Content.SecondReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(15));
        caller.Cancel();
        await handler.Content.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(15));
        handler.Content.Release.TrySetResult();

        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending.WaitAsync(TimeSpan.FromSeconds(15)));
        Assert.Equal(caller.Token, failure.CancellationToken);
        Assert.True(handler.Content.Disposed);
        Assert.Equal("ok", (await client.GenerateAsync("after", target: "openai-compat:model").WaitAsync(TimeSpan.FromSeconds(15))).Text);
    }

    private static AsyncClient Client(string provider, Uri baseUri) => new(
        [ProviderSettings.Of(provider, baseUri.ToString(), "key")], ProviderRegistry.CreateDefault());

    private static AsyncClient StreamingClient(GatedSseHandler handler) => new(
        [ProviderSettings.Of("openai-compat", "https://fixture.invalid", "key", transport: handler, limits: new RateLimits(maxConcurrent: 1))],
        ProviderRegistry.CreateDefault());

    private static HttpRequestMessage CreateRequest(RedirectRequestContext context, bool includeHeaders)
    {
        var request = new HttpRequestMessage(context.Method, context.Uri);
        if (context.IncludeBody) request.Content = new StringContent("{}", System.Text.Encoding.UTF8, "application/json");
        if (includeHeaders && context.IncludeOriginBoundHeaders) request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", "key");
        return request;
    }

    private static HttpRequestMessage CreateFixtureRequest(RedirectRequestContext context, RedirectStimulus stimulus)
    {
        var request = new HttpRequestMessage(context.Method, context.Uri);
        if (context.IncludeBody && stimulus.Body == "json") request.Content = new StringContent("{}", Encoding.UTF8, "application/json");
        if (stimulus.HeaderClasses.Contains("credential", StringComparer.Ordinal) && context.IncludeOriginBoundHeaders)
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", "key");
        if (context.IncludeOriginBoundHeaders && stimulus.HeaderClasses.Contains("configured", StringComparer.Ordinal))
        {
            request.Headers.TryAddWithoutValidation("Accept", "application/configured");
            request.Headers.TryAddWithoutValidation("X-Configured", "fixture");
        }
        if (context.IncludeOriginBoundHeaders && stimulus.HeaderClasses.Contains("cookie", StringComparer.Ordinal))
            request.Headers.TryAddWithoutValidation("Cookie", "literal=initial");
        return request;
    }

    private static void AssertFixtureWireFacts(RedirectStimulus stimulus, IReadOnlyList<ObservedRequest> requests)
    {
        Assert.Equal(stimulus.Method, requests[0].Method);
        Assert.Equal(stimulus.Body == "json" ? "{}" : "", requests[0].Body);
        Assert.Equal(new Uri(new Uri("https://first.example"), stimulus.Path).AbsolutePath, requests[0].Uri.AbsolutePath);
        switch (stimulus.Id)
        {
            case "same-origin":
                Assert.Equal("POST", requests[1].Method); Assert.Equal("{}", requests[1].Body);
                Assert.True(requests[1].Has("Authorization")); Assert.True(requests[1].Has("X-Configured")); break;
            case "post-rewrite":
                Assert.Equal("GET", requests[1].Method); Assert.Equal("", requests[1].Body);
                Assert.False(requests[1].Has("Content-Length")); Assert.False(requests[1].Has("Transfer-Encoding")); break;
            case "cross-origin-sticky":
                Assert.Equal("second.example", requests[1].Uri.Host);
                Assert.False(requests[1].Has("Authorization")); Assert.False(requests[2].Has("Authorization"));
                Assert.False(requests[2].Has("X-Configured")); break;
            case "safe-upgrade":
                Assert.Equal("https", requests[1].Uri.Scheme); Assert.True(requests[1].Has("Authorization")); break;
            case "relative-query-fragment":
                Assert.Equal("?page=2", requests[1].Uri.Query); break;
            case "terminal-missing-location":
                Assert.Single(requests); break;
            case "cookies":
                Assert.Contains("literal=initial", requests[0].Header("Cookie"), StringComparison.Ordinal);
                Assert.Contains("one=1", requests[1].Header("Cookie"), StringComparison.Ordinal);
                Assert.Contains("two=2", requests[1].Header("Cookie"), StringComparison.Ordinal);
                Assert.DoesNotContain("literal=initial", requests[1].Header("Cookie"), StringComparison.Ordinal); break;
            case "unsupported-userinfo":
                Assert.Single(requests); break;
            default: throw new InvalidOperationException($"Unhandled shared redirect stimulus '{stimulus.Id}'.");
        }
    }

    private static RedirectStimulus LoadStimulus(string id)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "redirects", "provider_redirects.json");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var item = document.RootElement.GetProperty("cases").EnumerateArray()
            .Single(candidate => candidate.GetProperty("id").GetString() == id);
        var responses = item.GetProperty("responses").EnumerateArray()
            .Select(response => new RedirectResponseStimulus(
                response.GetProperty("status").GetInt32(),
                response.TryGetProperty("location", out var location) ? location.GetString() : null,
                response.TryGetProperty("set_cookie", out var cookies)
                    ? cookies.EnumerateArray().Select(static cookie => cookie.GetString()!).ToArray()
                    : []))
            .ToArray();
        return new RedirectStimulus(responses);
    }

    private static IReadOnlyList<RedirectStimulus> LoadAllStimuli()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "redirects", "provider_redirects.json");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        return document.RootElement.GetProperty("cases").EnumerateArray()
            .Select(item => new RedirectStimulus(
                item.GetProperty("id").GetString()!,
                item.GetProperty("request").GetProperty("method").GetString()!,
                item.GetProperty("request").GetProperty("path").GetString()!,
                item.GetProperty("request").GetProperty("body").GetString()!,
                item.GetProperty("request").GetProperty("header_classes").EnumerateArray().Select(static value => value.GetString()!).ToArray(),
                item.GetProperty("responses").EnumerateArray().Select(response => new RedirectResponseStimulus(
                    response.GetProperty("status").GetInt32(),
                    response.TryGetProperty("location", out var location) ? location.GetString() : null,
                    response.TryGetProperty("set_cookie", out var cookies)
                        ? cookies.EnumerateArray().Select(static cookie => cookie.GetString()!).ToArray()
                        : [])).ToArray()))
            .ToArray();
    }

    private sealed record RedirectStimulus(string Id, string Method, string Path, string Body, IReadOnlyList<string> HeaderClasses, IReadOnlyList<RedirectResponseStimulus> Responses)
    {
        internal RedirectStimulus(IReadOnlyList<RedirectResponseStimulus> responses) : this("same-origin", "POST", "/v1/chat/completions", "json", [], responses) { }
    }
    private sealed record RedirectResponseStimulus(int Status, string? Location, IReadOnlyList<string> SetCookies);

    private sealed class StimulusHandler(IEnumerable<RedirectResponseStimulus> responses) : HttpMessageHandler
    {
        private readonly Queue<RedirectResponseStimulus> _responses = new(responses);
        internal int SendCount { get; private set; }
        internal System.Collections.Concurrent.ConcurrentQueue<ObservedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCount++;
            var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
            var contentHeaders = request.Content is null
                ? Enumerable.Empty<KeyValuePair<string, IEnumerable<string>>>()
                : request.Content.Headers;
            Requests.Enqueue(new ObservedRequest(request.Method.Method, request.RequestUri!, body, request.Headers.Concat(contentHeaders).ToDictionary(static h => h.Key, static h => string.Join(",", h.Value), StringComparer.OrdinalIgnoreCase)));
            var response = _responses.Count > 0 ? _responses.Dequeue() : new RedirectResponseStimulus(200, null, []);
            var message = new HttpResponseMessage((System.Net.HttpStatusCode)response.Status)
            {
                Content = new StringContent("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}"""),
            };
            if (response.Location is not null) message.Headers.TryAddWithoutValidation("Location", response.Location);
            foreach (var cookie in response.SetCookies) message.Headers.TryAddWithoutValidation("Set-Cookie", cookie);
            return message;
        }
    }

    private sealed record ObservedRequest(string Method, Uri Uri, string Body, IReadOnlyDictionary<string, string> Headers)
    {
        internal bool Has(string name) => Headers.ContainsKey(name);
        internal string Header(string name) => Headers.TryGetValue(name, out var value) ? value : "";
    }

    private sealed class ConcurrentCookieRedirectHandler : HttpMessageHandler
    {
        private int _initial;
        internal TaskCompletionSource BothInitial { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal System.Collections.Concurrent.ConcurrentQueue<ObservedRequest> Requests { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
            Requests.Enqueue(new ObservedRequest(request.Method.Method, request.RequestUri!, body, request.Headers.ToDictionary(static h => h.Key, static h => string.Join(",", h.Value), StringComparer.OrdinalIgnoreCase)));
            if (Interlocked.Increment(ref _initial) <= 2)
            {
                if (_initial == 2) BothInitial.TrySetResult();
                await Release.Task.WaitAsync(cancellationToken);
                var unsafeTarget = request.Content?.ReadAsStringAsync(cancellationToken).Result.Contains("\"a\"", StringComparison.Ordinal) == true;
                var response = new HttpResponseMessage(HttpStatusCode.TemporaryRedirect);
                response.Headers.Location = new Uri(unsafeTarget ? "https://second.example/next" : "https://first.example/next");
                response.Headers.TryAddWithoutValidation("Set-Cookie", unsafeTarget ? "unsafe=one; Path=/" : "safe=one; Path=/");
                return response;
            }
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}""") };
        }
    }

    private sealed class SendCountingHandler(HttpMessageHandler innerHandler) : DelegatingHandler(innerHandler)
    {
        private int _sendCount;
        internal int SendCount => Volatile.Read(ref _sendCount);
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _sendCount);
            return base.SendAsync(request, cancellationToken);
        }
    }

    private sealed class GatedSseHandler : HttpMessageHandler
    {
        private int _calls;
        internal GatedSseContent Content { get; } = new();
        internal int SendCalls => Volatile.Read(ref _calls);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Interlocked.Increment(ref _calls) == 1)
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = Content });
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}""", Encoding.UTF8, "application/json"),
            });
        }
    }

    private sealed class GatedSseContent : HttpContent
    {
        internal TaskCompletionSource SecondReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool Disposed { get; private set; }

        internal GatedSseContent() => Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/event-stream");
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => Task.CompletedTask;
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task<Stream> CreateContentReadStreamAsync(CancellationToken cancellationToken) =>
            Task.FromResult<Stream>(new GatedSseStream(SecondReadStarted, CancellationObserved, Release, cancellationToken));
        protected override void Dispose(bool disposing) { if (disposing) Disposed = true; base.Dispose(disposing); }
    }

    private sealed class GatedSseStream(
        TaskCompletionSource secondReadStarted,
        TaskCompletionSource cancellationObserved,
        TaskCompletionSource release,
        CancellationToken contentToken) : Stream
    {
        private readonly byte[] _first = Encoding.UTF8.GetBytes("data: {\"choices\":[{\"delta\":{\"content\":\"chunk\"}}]}\n\n");
        private int _reads;
        public override bool CanRead => true; public override bool CanSeek => false; public override bool CanWrite => false;
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
            if (Interlocked.Increment(ref _reads) == 1) { _first.CopyTo(buffer); return _first.Length; }
            secondReadStarted.TrySetResult();
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(contentToken, cancellationToken);
            try { await Task.Delay(Timeout.InfiniteTimeSpan, linked.Token); return 0; }
            catch (OperationCanceledException) { cancellationObserved.TrySetResult(); await release.Task; throw; }
        }
    }
}
