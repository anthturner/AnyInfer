using AnyInfer.Config;
using AnyInfer.Credentials;

namespace AnyInfer.Examples.Cases;

/// <summary>Executes and asserts when credential references are admitted, resolved, and refused.</summary>
internal static class CredentialReferenceCases
{
    private const string KeyVariable = "ANYINFER_RECIPE_OFFLINE_KEY";

    /// <summary>An env:// key is not read at load or client construction; the first call resolves it.</summary>
    [ExampleCase("credentials.env-resolves-at-first-call")]
    internal static async Task EnvResolvesAtFirstCall()
    {
        try
        {
            Environment.SetEnvironmentVariable(KeyVariable, null);
            var config = CredentialReferenceExample.Load(Document($"env://{KeyVariable}"));
            ExampleSupport.Require(
                config.Providers.Single().ApiKey == $"env://{KeyVariable}",
                "Loading did not keep the env:// reference unresolved.");

            var missing = new RecipeChatHandler();
            var failure = await RecipeSupport.CaptureAsync(() =>
                CredentialReferenceExample.AskAsync(Offline(config, missing), "Say hello."));
            ExampleSupport.Require(
                failure is CredentialException && missing.Requests == 0 && missing.Disposals == 1,
                "An unset env:// reference did not fail with CredentialException before any request.");

            Environment.SetEnvironmentVariable(KeyVariable, "offline-recipe-key");
            var present = new RecipeChatHandler();
            var result = await CredentialReferenceExample.AskAsync(Offline(config, present), "Say hello.");
            ExampleSupport.Require(
                result.Text == "hello"
                && present.Authorizations.Single() == "Bearer offline-recipe-key"
                && present.Disposals == 1,
                "A set env:// reference was not resolved and sent as a bearer token at the first call.");
        }
        finally
        {
            Environment.SetEnvironmentVariable(KeyVariable, null);
        }
    }

    /// <summary>A credential:// reference loads, then always fails natively before any request.</summary>
    [ExampleCase("credentials.keyring-reference-fails")]
    internal static async Task KeyringReferenceFails()
    {
        var config = CredentialReferenceExample.Load(Document("credential://system/anyinfer-demo"));
        var transport = new RecipeChatHandler();
        var failure = await RecipeSupport.CaptureAsync(() =>
            CredentialReferenceExample.AskAsync(Offline(config, transport), "Say hello."));
        ExampleSupport.Require(
            failure is CredentialException && transport.Requests == 0 && transport.Disposals == 1,
            "A credential:// reference did not fail with CredentialException before any request.");
    }

    /// <summary>A reference no resolver handles fails at load; an application resolver admits and resolves it.</summary>
    [ExampleCase("credentials.application-resolver")]
    internal static async Task ApplicationResolver()
    {
        var document = Document("app-secret://chat-key");
        var unhandled = RecipeSupport.Capture(() => CredentialReferenceExample.Load(document));
        ExampleSupport.Require(
            unhandled is ConfigException,
            "A reference whose scheme no resolver handles was not rejected at load.");

        var resolver = CredentialReferenceExample.WithApplicationSecrets(
            new Dictionary<string, string> { ["chat-key"] = "offline-app-secret" });
        var config = CredentialReferenceExample.Load(document, resolver);
        var transport = new RecipeChatHandler();
        var result = await CredentialReferenceExample.AskAsync(Offline(config, transport), "Say hello.", resolver);
        ExampleSupport.Require(
            result.Text == "hello"
            && transport.Authorizations.Single() == "Bearer offline-app-secret"
            && transport.Disposals == 1,
            "The application resolver did not resolve its reference at the first call.");

        var empty = CredentialReferenceExample.WithApplicationSecrets(new Dictionary<string, string>());
        var absent = new RecipeChatHandler();
        var failure = await RecipeSupport.CaptureAsync(() =>
            CredentialReferenceExample.AskAsync(Offline(CredentialReferenceExample.Load(document, empty), absent), "Say hello.", empty));
        ExampleSupport.Require(
            failure is CredentialException && absent.Requests == 0,
            "A missing application secret did not fail with CredentialException before any request.");
    }

    private static string Document(string apiKey) => $$"""
        {"format_version": 1,
         "providers": [{"id": "openai-compat", "base_url": "{{ExampleSupport.BaseUrl}}", "api_key": "{{apiKey}}"}],
         "default_route": ["{{ExampleSupport.Target}}"]}
        """;

    private static AnyInferConfig Offline(AnyInferConfig config, HttpMessageHandler transport) =>
        new(
            config.Providers.Select(provider => ExampleSupport.WithTransport(provider, transport)),
            config.Route,
            config.Repair,
            cache: config.Cache,
            operationRoutes: config.OperationRoutes);
}
