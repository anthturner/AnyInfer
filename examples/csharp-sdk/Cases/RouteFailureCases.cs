using System.Net;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes the routing, retry and failure recipes published in the fallback guide.</summary>
internal static class RouteFailureCases
{
    private const string Unavailable = "The OpenAI-compatible service returned HTTP 503.";

    [ExampleCase("route-failure.default-route")]
    internal static async Task DefaultRoute()
    {
        var primary = new GuideScripts.ChatHandler(
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable),
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        var generation = await RouteFailureExample.GenerateWithDefaultRouteAsync(
            [GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")],
            ["primary:demo", "backup:demo"]);
        ExampleSupport.Require(generation.Text == "hello"
            && generation.Target?.ToString() == "backup:demo"
            && RouteFailureExample.DescribeAttempts(generation).SequenceEqual(
            [
                "primary:demo: retried",
                $"   ProviderUnavailableException: {Unavailable}",
                "primary:demo: failed",
                $"   ProviderUnavailableException: {Unavailable}",
                "backup:demo: ok",
            ])
            && primary.RequestCount == 2
            && backup.RequestCount == 1,
            "The default route did not retry its first target once and then fall back.");
    }

    [ExampleCase("route-failure.attempt-trail")]
    internal static async Task AttemptTrail()
    {
        var primary = new GuideScripts.ChatHandler(GuideScripts.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        var generation = await RoutingExample.RunAsync(
            [GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")],
            new Route(["primary:demo", "backup:demo"], retry: new Retry(1)));
        var lines = RouteFailureExample.DescribeAttempts(generation);
        ExampleSupport.Require(lines.SequenceEqual(
            [
                "primary:demo: failed",
                $"   ProviderUnavailableException: {Unavailable}",
                "backup:demo: ok",
            ])
            && generation.Attempts[0].Error is ProviderUnavailableException { HttpStatus: 503, Retryable: true }
            && generation.Attempts[1].Timing is not null,
            $"The attempt trail was [{string.Join(" | ", lines)}].");
    }

    [ExampleCase("route-failure.all-targets-failed")]
    internal static async Task AllTargetsFailed()
    {
        var primary = new GuideScripts.ChatHandler(
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable),
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new GuideScripts.ChatHandler(
            GuideScripts.Status(HttpStatusCode.Unauthorized),
            GuideScripts.Status(HttpStatusCode.Unauthorized));
        await using var client = new AsyncClient([GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")]);
        // Without the health gate the second call below attempts the failed primary target again.
        var route = new Route(["primary:demo", "backup:demo"], retry: new Retry(1), healthGate: false);
        var alerts = new StringWriter();
        var generation = await RouteFailureExample.TryGenerateAsync(client, route, alerts);
        var nl = Environment.NewLine;
        ExampleSupport.Require(generation is null
            && alerts.ToString() == $"primary:demo: failed: {Unavailable}{nl}backup:demo: failed: The OpenAI-compatible service returned HTTP 401.{nl}",
            $"Exhausted targets were reported as '{alerts}'.");

        var failure = await GuideScripts.ExpectThrowsAsync<AllTargetsFailedException>(
            () => client.GenerateAsync("Say hello.", route: route),
            "Exhausting every target did not raise AllTargetsFailedException.");
        ExampleSupport.Require(failure.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["failed", "failed"])
            && failure.Attempts[0].Error is ProviderUnavailableException
            && failure.Attempts[1].Error is AuthException
            && primary.RequestCount == 2
            && backup.RequestCount == 2,
            "AllTargetsFailedException did not carry each ordered attempt.");
    }

    [ExampleCase("route-failure.context-window")]
    internal static async Task ContextWindow()
    {
        var small = new GuideScripts.ChatHandler(GuideScripts.Status((HttpStatusCode)422, "This model's maximum context length is 8192 tokens."));
        var backup = new GuideScripts.ChatHandler();
        var large = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        var route = RouteFailureExample.OverflowAware(["small:demo", "backup:demo"], ["large:demo"]);
        var generation = await RoutingExample.RunAsync(
            [GuideScripts.Instance(small, "small"), GuideScripts.Instance(backup, "backup"), GuideScripts.Instance(large, "large")],
            route);
        ExampleSupport.Require(generation.Target?.ToString() == "large:demo"
            && generation.Attempts.Select(static attempt => $"{attempt.Target} {attempt.Outcome}").SequenceEqual(["small:demo failed", "large:demo ok"])
            && generation.Attempts[0].Error is ContextLengthException
            && small.RequestCount == 1
            && backup.RequestCount == 0
            && large.RequestCount == 1,
            "A context-window overflow did not switch to the context-window chain.");
    }

    [ExampleCase("route-failure.retry")]
    internal static async Task RetryPolicy()
    {
        var patient = RouteFailureExample.Patient(["primary:demo"]);
        ExampleSupport.Require(patient.Retry == new Retry(3, 0.5, 30) && patient.HealthGate && patient.HealthTtlS == 30,
            "The patient route did not keep its retry policy.");

        var flaky = new GuideScripts.ChatHandler(
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable),
            GuideScripts.Status((HttpStatusCode)429),
            GuideScripts.Text("hello"));
        var recovered = await RoutingExample.RunAsync(
            [GuideScripts.Instance(flaky, "primary")],
            new Route(["primary:demo"], retry: patient.Retry with { BackoffBaseS = 0, BackoffMaxS = 0 }));
        ExampleSupport.Require(recovered.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["retried", "retried", "ok"])
            && recovered.Attempts[1].Error is RateLimitException
            && flaky.RequestCount == 3,
            "Retryable failures were not retried on the same target.");

        var denied = new GuideScripts.ChatHandler(GuideScripts.Status(HttpStatusCode.Unauthorized));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text("hello"));
        var fellBack = await RoutingExample.RunAsync(
            [GuideScripts.Instance(denied, "primary"), GuideScripts.Instance(backup, "backup")],
            new Route(["primary:demo", "backup:demo"], retry: new Retry(3, 0, 0)));
        ExampleSupport.Require(fellBack.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["failed", "ok"])
            && fellBack.Attempts[0].Error is AuthException
            && denied.RequestCount == 1,
            "An authentication failure was retried instead of falling back.");
    }

    [ExampleCase("route-failure.health-gate")]
    internal static async Task HealthGate()
    {
        var primary = new GuideScripts.ChatHandler(
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable),
            GuideScripts.Status(HttpStatusCode.ServiceUnavailable));
        var backup = new GuideScripts.ChatHandler(GuideScripts.Text("hello"), GuideScripts.Text("hello"), GuideScripts.Text("hello"));
        await using var client = new AsyncClient([GuideScripts.Instance(primary, "primary"), GuideScripts.Instance(backup, "backup")]);
        var gated = new Route(["primary:demo", "backup:demo"], retry: new Retry(1));

        var first = await client.GenerateAsync("Say hello.", route: gated);
        var second = await client.GenerateAsync("Say hello.", route: gated);
        ExampleSupport.Require(first.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["failed", "ok"])
            && second.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["skipped_unhealthy", "ok"])
            && second.Attempts[0].Error is null
            && primary.RequestCount == 1,
            "A recently failed target was not skipped by the health gate.");

        var ungated = RouteFailureExample.Ungated(["primary:demo", "backup:demo"]);
        var third = await client.GenerateAsync("Say hello.", route: new Route(ungated.Targets, retry: new Retry(1), healthGate: ungated.HealthGate));
        ExampleSupport.Require(!ungated.HealthGate
            && third.Attempts.Select(static attempt => attempt.Outcome).SequenceEqual(["failed", "ok"])
            && primary.RequestCount == 2
            && backup.RequestCount == 3,
            "A route without a health gate skipped a recently failed target.");
    }
}
