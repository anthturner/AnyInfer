using System.Text.Json;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Controls that consume the independently recorded TEI wire witnesses.</summary>
public sealed class TeiCassetteTests
{
    [Theory]
    [InlineData("tei_embed.json", "POST", "/embed")]
    [InlineData("tei_info.json", "GET", "/info")]
    [InlineData("tei_rerank.json", "POST", "/rerank")]
    public void Fresh_cassette_contains_one_literal_sanitized_interaction(string name, string method, string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(CassettePath(name)));
        var interaction = Assert.Single(document.RootElement.GetProperty("interactions").EnumerateArray());
        Assert.Equal(method, interaction.GetProperty("method").GetString());
        Assert.EndsWith(path, interaction.GetProperty("url").GetString(), StringComparison.Ordinal);
        Assert.Equal(200, interaction.GetProperty("status").GetInt32());
        Assert.False(interaction.GetProperty("body").GetString()!.Contains("Bearer ", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Embed_and_rerank_witnesses_remain_distinct_provider_answers()
    {
        using var embed = JsonDocument.Parse(File.ReadAllText(CassettePath("tei_embed.json")));
        using var rerank = JsonDocument.Parse(File.ReadAllText(CassettePath("tei_rerank.json")));
        using var info = JsonDocument.Parse(File.ReadAllText(CassettePath("tei_info.json")));

        Assert.Equal(JsonValueKind.Array, JsonDocument.Parse(Body(embed)).RootElement.ValueKind);
        var ranks = JsonDocument.Parse(Body(rerank)).RootElement;
        Assert.Equal(JsonValueKind.Array, ranks.ValueKind);
        Assert.True(ranks[0].GetProperty("index").GetInt32() >= 0);
        var metadata = JsonDocument.Parse(Body(info)).RootElement;
        Assert.Equal("BAAI/bge-small-en-v1.5", metadata.GetProperty("model_id").GetString());
        Assert.Equal("1.9.4", metadata.GetProperty("version").GetString());
    }

    private static string CassettePath(string name) => Path.Combine(AppContext.BaseDirectory, "tei-cassettes", name);

    private static string Body(JsonDocument document) => document.RootElement.GetProperty("interactions")[0].GetProperty("body").GetString()!;
}
