using AnyInfer.Providers;

namespace AnyInfer.Examples;

/// <summary>Builds inert provider-setup metadata for a configuration or UI boundary.</summary>
public static class SetupExample
{
    /// <summary>Builds declarative setup facts without resolving credentials or creating a provider.</summary>
    public static ProviderSetupSpec Create()
    {
        return new ProviderSetupSpec(
            fields:
            [
                new SetupField("base_url", "API base URL", kind: "endpoint", required: true),
                new SetupField(
                    "api_key",
                    "API key",
                    kind: "secret",
                    envVar: "ANYINFER_API_KEY"),
                new SetupField(
                    "access_token",
                    "Access token",
                    kind: "secret",
                    envVar: "ANYINFER_ACCESS_TOKEN"),
                new SetupField(
                    "api_version",
                    "API version",
                    kind: "choice",
                    advanced: true,
                    defaultValue: "v1",
                    choices: ["v1", "v2"]),
            ],
            hostShorthand: new HostShorthand("https", 443),
            anyOf: [["api_key", "access_token"]],
            requirementNote: "Supply either an API key or an access token.");
    }
}
