using AnyInfer.Json;
using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public constructor controls for opaque wire session-state protocol data.</summary>
public sealed class RichGenerationSessionStateTests
{
    [Fact]
    public void Session_state_defaults_to_null_and_named_state_is_an_outer_snapshot()
    {
        var state = new JsonObject([new JsonProperty("turn", new JsonInteger(3))]);
        var independent = Request();
        var sessionRequest = Request(sessionState: state);

        Assert.Null(independent.SessionState);
        Assert.NotNull(sessionRequest.SessionState);
        Assert.NotSame(state, sessionRequest.SessionState);
        Assert.Equal(3, Assert.IsType<JsonInteger>(Property(sessionRequest.SessionState!, "turn")).Value);
    }

    [Fact]
    public void Existing_positional_extra_options_and_named_session_state_remain_compatible()
    {
        var options = new JsonObject([new JsonProperty("legacy", new JsonBoolean(true))]);
        var legacy = new WireRequest(
            "model", [Message.User("prompt")], new Sampling(), null, null, false, 120, 1_048_576,
            "response", null, "auto", null, null, null, false, null, options);
        var named = Request(sessionState: new JsonObject([new JsonProperty("opened", new JsonBoolean(true))]));

        Assert.True(Assert.IsType<JsonBoolean>(Property(legacy.ExtraOptions, "legacy")).Value);
        Assert.Null(legacy.SessionState);
        Assert.True(Assert.IsType<JsonBoolean>(Property(named.SessionState!, "opened")).Value);
    }

    private static WireRequest Request(JsonObject? sessionState = null) =>
        new("model", [Message.User("prompt")], new Sampling(), sessionState: sessionState);

    private static JsonValue Property(JsonObject source, string name) =>
        source.TryGetValue(name, out var value) ? value : throw new Xunit.Sdk.XunitException($"Missing {name}.");
}
