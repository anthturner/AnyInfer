using AnyInfer.Providers;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Tests for inert provider setup metadata.</summary>
public sealed class ProviderSetupTests
{
    [Fact]
    public void Defaults_modes_and_empty_descriptive_values_follow_the_setup_contract()
    {
        var defaults = new ProviderSetupSpec();
        Assert.Equal("discover-or-manual", defaults.ModelSelection);
        Assert.Empty(defaults.Fields);
        Assert.Empty(defaults.AnyOf);
        Assert.Equal("", defaults.RequirementNote);
        Assert.Equal("", new ProviderSetupSpec(requirementNote: null!).RequirementNote);

        var field = new SetupField("endpoint", "Endpoint", helpText: null, placeholder: null, envVar: null, defaultValue: null);
        Assert.Equal("", field.HelpText);
        Assert.Equal("", field.Placeholder);
        Assert.Equal("", field.EnvVar);
        Assert.Equal("", field.DefaultValue);
        Assert.False(new SetupField("plain", "Plain").Required);
        Assert.False(new SetupField("explicit", "Explicit", required: false, advanced: false).Required);
        Assert.False(new SetupField("explicit", "Explicit", required: false, advanced: false).Advanced);
        Assert.Equal("manual-only", new ProviderSetupSpec(modelSelection: "manual-only").ModelSelection);
        Assert.Throws<ArgumentException>(() => new ProviderSetupSpec(modelSelection: "automatic"));
        Assert.Equal("", new SetupField("endpoint", "Endpoint", defaultValue: "").DefaultValue);
        Assert.Equal("", new SetupField("endpoint-env", "Endpoint", envVar: "").EnvVar);
        Assert.Equal("", new SetupField("mode", "Mode", "choice", defaultValue: "", choices: ["a"]).DefaultValue);
    }

    [Fact]
    public void Fields_groups_labels_and_blank_values_are_exposed_in_declared_order()
    {
        var spec = new ProviderSetupSpec(
            [new SetupField("token", "Token", "secret"), new SetupField("oauth", "OAuth token", "secret"), new SetupField("endpoint", "Endpoint", advanced: true)],
            anyOf: [["token", "oauth"], [], ["unknown"]], requirementNote: "Choose a credential.");

        Assert.Equal(["token", "oauth"], spec.EssentialFields.Select(field => field.Key));
        Assert.Equal(["endpoint"], spec.AdvancedFields.Select(field => field.Key));
        Assert.Equal("Token", spec.LabelFor("token"));
        Assert.Equal("missing", spec.LabelFor("missing"));
        Assert.Equal("Choose a credential.", spec.RequirementNote);
        Assert.Equal([[], ["unknown"]], spec.UnsatisfiedGroups(new Dictionary<string, string> { ["token"] = "   ", ["oauth"] = "value" }));
        Assert.Equal([ ["token", "oauth"], [], ["unknown"] ], spec.UnsatisfiedGroups(new Dictionary<string, string> { ["token"] = " ", ["unknown"] = "" }));
    }

    [Fact]
    public void Groups_are_deep_snapshots_and_advanced_group_members_are_refused()
    {
        var first = new List<string> { "token" };
        var groups = new List<IEnumerable<string>> { first };
        var spec = new ProviderSetupSpec(anyOf: groups);
        first[0] = "changed";
        groups.Add(["later"]);

        Assert.Equal(["token"], Assert.Single(spec.AnyOf));
        Assert.Throws<ArgumentException>(() => new ProviderSetupSpec(
            [new SetupField("token", "Token", advanced: true)], anyOf: [["token"]]));
    }

    [Theory]
    [InlineData(" myserver ", "http://myserver:11434")]
    [InlineData("myserver:8080", "http://myserver:8080")]
    [InlineData("myserver/path", "http://myserver/path:11434")]
    [InlineData("host:8080/path", "http://host:8080/path")]
    [InlineData("host/path:part", "http://host/path:part:11434")]
    [InlineData(" https://example.test:9443/v1 ", "https://example.test:9443/v1")]
    public void Host_shorthand_uses_the_literal_python_expansion_algorithm(string input, string expected) =>
        Assert.Equal(expected, new HostShorthand("http", 11434).Expand(input));
}
