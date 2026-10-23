using System.Net;
using System.Net.Http;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Stateful cookie controls for a single adapter redirect sender.</summary>
public sealed class RedirectCookieJarTests
{
    [Fact]
    public void Initial_literal_cookie_is_preserved_but_redirect_cookie_is_recalculated()
    {
        var jar = new RedirectCookieJar();
        var origin = new Uri("https://fixture.example/start");
        using var initial = new HttpRequestMessage(HttpMethod.Get, origin);
        initial.Headers.Add("Cookie", "literal=one");
        jar.Apply(origin, initial, isRedirect: false);
        Assert.Equal("literal=one", string.Join(";", initial.Headers.GetValues("Cookie")));

        using var response = new HttpResponseMessage(HttpStatusCode.Redirect);
        response.Headers.TryAddWithoutValidation("Set-Cookie", "jar=two; Path=/");
        jar.Observe(origin, response.Headers);
        using var followed = new HttpRequestMessage(HttpMethod.Get, new Uri("https://fixture.example/next"));
        jar.Apply(followed.RequestUri!, followed, isRedirect: true);
        Assert.DoesNotContain("literal=one", string.Join(";", followed.Headers.GetValues("Cookie")), StringComparison.Ordinal);
        Assert.Contains("jar=two", string.Join(";", followed.Headers.GetValues("Cookie")), StringComparison.Ordinal);
    }

    [Fact]
    public void Final_response_cookie_is_available_to_the_next_operation_and_bad_neighbor_is_ignored()
    {
        var jar = new RedirectCookieJar();
        var uri = new Uri("https://fixture.example/path/item");
        using var response = new HttpResponseMessage(HttpStatusCode.OK);
        response.Headers.TryAddWithoutValidation("Set-Cookie", "good=one; Path=/path");
        response.Headers.TryAddWithoutValidation("Set-Cookie", "not-a-cookie");
        response.Headers.TryAddWithoutValidation("Set-Cookie", "good=two; Path=/path");
        jar.Observe(uri, response.Headers);
        using var request = new HttpRequestMessage(HttpMethod.Get, uri);
        jar.Apply(uri, request, isRedirect: false);
        Assert.Contains("good=two", string.Join(";", request.Headers.GetValues("Cookie")), StringComparison.Ordinal);
    }

    [Fact]
    public void Capacity_controls_do_not_reintroduce_default_cookie_eviction_limits()
    {
        var jar = new RedirectCookieJar();
        var uri = new Uri("https://fixture.example/");
        using var response = new HttpResponseMessage(HttpStatusCode.OK);
        for (var index = 0; index < 305; index++) response.Headers.TryAddWithoutValidation("Set-Cookie", $"c{index}=v; Path=/");
        response.Headers.TryAddWithoutValidation("Set-Cookie", $"long={new string('x', 4097)}; Path=/");
        jar.Observe(uri, response.Headers);
        using var request = new HttpRequestMessage(HttpMethod.Get, uri);
        jar.Apply(uri, request, isRedirect: false);
        var cookie = string.Join(";", request.Headers.GetValues("Cookie"));
        Assert.Contains("c304=v", cookie, StringComparison.Ordinal);
        Assert.Contains("long=", cookie, StringComparison.Ordinal);
    }

    [Fact]
    public void Separate_adapter_jars_remain_isolated_even_when_transport_ownership_is_shared()
    {
        var first = new RedirectCookieJar();
        var second = new RedirectCookieJar();
        var uri = new Uri("https://fixture.example/");
        using var response = new HttpResponseMessage(HttpStatusCode.OK);
        response.Headers.TryAddWithoutValidation("Set-Cookie", "first=one; Path=/");
        first.Observe(uri, response.Headers);
        using var firstRequest = new HttpRequestMessage(HttpMethod.Get, uri);
        using var secondRequest = new HttpRequestMessage(HttpMethod.Get, uri);
        first.Apply(uri, firstRequest, isRedirect: false);
        second.Apply(uri, secondRequest, isRedirect: false);

        Assert.Contains("first=one", string.Join(";", firstRequest.Headers.GetValues("Cookie")), StringComparison.Ordinal);
        Assert.False(secondRequest.Headers.Contains("Cookie"));
    }

    [Fact]
    public async Task Concurrent_cookie_observation_and_application_leave_no_shared_mutable_operation_state()
    {
        var jar = new RedirectCookieJar();
        var uri = new Uri("https://fixture.example/");
        var tasks = Enumerable.Range(0, 24).Select(async index =>
        {
            using var response = new HttpResponseMessage(HttpStatusCode.OK);
            response.Headers.TryAddWithoutValidation("Set-Cookie", $"c{index}=v; Path=/");
            jar.Observe(uri, response.Headers);
            using var request = new HttpRequestMessage(HttpMethod.Get, uri);
            jar.Apply(uri, request, isRedirect: false);
            await Task.Yield();
            Assert.NotEmpty(request.Headers.GetValues("Cookie"));
        });

        await Task.WhenAll(tasks);
    }
}
