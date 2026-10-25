using AnyInfer.Capabilities;
using AnyInfer.Catalog;
using AnyInfer.Providers;
using PeterO.Numbers;

namespace AnyInfer.Examples.Cases;

/// <summary>Asserts which documented operations are pure and which build an adapter, resolve credentials, or load TLS material.</summary>
internal static class MetadataBoundaryCases
{
    private const string UnsetKey = "env://ANYINFER_RECIPE_UNSET_KEY";

    /// <summary>Catalog, capability, and pricing queries resolve no credential and build no adapter; discovery does both.</summary>
    [ExampleCase("metadata-boundary.pure-queries-resolve-nothing")]
    internal static async Task PureQueriesResolveNothing()
    {
        Environment.SetEnvironmentVariable("ANYINFER_RECIPE_UNSET_KEY", null);
        var factoryCalls = 0;
        var registry = new ProviderRegistry(
        [
            new ProviderDescriptor(
                "demo",
                "Demo",
                (_, _) =>
                {
                    factoryCalls++;
                    throw new InvalidOperationException("A pure query constructed an adapter.");
                }),
        ]);
        var catalog = new global::AnyInfer.Catalog.Catalog(
            aliases: new Dictionary<string, AliasEntry>
            {
                ["tier"] = new AliasEntry("tier", targets: new Dictionary<string, TargetEntry>
                {
                    ["demo-instance"] = new TargetEntry("demo-instance", Model: "demo-model"),
                }),
            });
        var pricing = new PricingTable(new Dictionary<string, IReadOnlyList<PricingEntry>>
        {
            ["demo-instance"] =
            [
                new PricingEntry("demo-model", new Pricing(EDecimal.FromString("3.25"), EDecimal.FromString("4.5")), "2026-10-17", "offline example"),
            ],
        });
        var observation = CatalogExample.Inspect(
            catalog,
            pricing,
            ProviderSettings.Of("demo", alias: "demo-instance", apiKey: UnsetKey),
            registry);
        ExampleSupport.Require(
            observation.Target is { ProviderId: "demo-instance", Model: "demo-model", ViaAlias: "tier" }
            && observation.Pricing is { Provenance: Provenance.Catalog }
            && observation.Capabilities.ContextWindow is null
            && factoryCalls == 0,
            "A pure catalog query resolved a credential, built an adapter, or invented an unknown fact.");

        var transport = new RecipeChatHandler();
        var discovery = await RecipeSupport.CaptureAsync(() => LifecycleExample.RunAsync(
            ExampleSupport.WithTransport(SettingsExample.Create(ExampleSupport.BaseUrl, UnsetKey), transport),
            "openai-compat"));
        ExampleSupport.Require(
            discovery is CredentialException && transport.Requests == 0 && transport.Disposals == 1,
            "Model discovery did not resolve the instance's credential before sending a request.");
    }

    /// <summary>TLS material is read when the first operation builds the SDK handler, not at settings or client construction.</summary>
    [ExampleCase("metadata-boundary.tls-material-loads-at-first-use")]
    internal static async Task TlsMaterialLoadsAtFirstUse()
    {
        var missing = Path.Combine(Path.GetTempPath(), $"anyinfer-missing-{Guid.NewGuid():N}.pem");
        var settings = ProviderSettings.Of(
            "openai-compat",
            baseUrl: "https://127.0.0.1:9/v1",
            verify: TlsVerification.FromPemBundle(missing),
            clientCertificate: ClientCertificate.FromPemFile(missing));
        await using (var client = new AsyncClient([settings]))
        {
            var failure = await RecipeSupport.CaptureAsync(() => client.GenerateAsync("Say hello.", target: ExampleSupport.Target));
            ExampleSupport.Require(
                failure is ConfigException,
                "A missing PEM file was not reported as ConfigException when the first call built the handler.");
        }

        var transport = new RecipeChatHandler();
        await using (var client = new AsyncClient([ExampleSupport.WithTransport(settings, transport)]))
        {
            var result = await client.GenerateAsync("Say hello.", target: ExampleSupport.Target);
            ExampleSupport.Require(
                result.Text == "hello" && transport.Requests == 1,
                "A supplied handler did not bypass SDK TLS material loading.");
        }

        ExampleSupport.Require(transport.Disposals == 1, "The client did not dispose the supplied handler once.");
    }
}
