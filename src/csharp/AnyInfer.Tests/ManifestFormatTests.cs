using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using AnyInfer.Json;
using AnyInfer.Manifest;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent byte-level controls for the manifest-specific JSON policies.</summary>
public sealed class ManifestFormatTests
{
    [Fact]
    public void Schema_digest_uses_manifest_canonical_bytes_for_large_integers_numbers_strings_and_nested_objects()
    {
        var schema = new JsonObject(
        [
            new JsonProperty("z", new JsonString("é\u007f\n")),
            new JsonProperty("big", new JsonInteger(BigInteger.Parse("10000000000000000000000000000000000000000000000000000000000000000000001"))),
            new JsonProperty("number", new JsonNumber(-0.0, "-0")),
            new JsonProperty("nested", new JsonObject([new JsonProperty("b", new JsonBoolean(false)), new JsonProperty("a", JsonNull.Instance)])),
        ]);
        const string canonical = "{\"big\":10000000000000000000000000000000000000000000000000000000000000000000001,\"nested\":{\"a\":null,\"b\":false},\"number\":-0.0,\"z\":\"\\u00e9\\u007f\\n\"}";
        var expected = "sha256:" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();

        Assert.Equal(expected, ManifestUtilities.SchemaDigest(schema));
    }

    [Theory]
    [InlineData(-0.0, "-0.0")]
    [InlineData(0.0001, "0.0001")]
    [InlineData(0.00001, "1e-05")]
    [InlineData(10000000000000000d, "1e+16")]
    public void Internal_manifest_writer_uses_python_number_thresholds(double value, string expected)
    {
        Assert.Equal(expected, JsonWriter.WriteManifestCanonical(new JsonNumber(value, "ignored")));
    }

    [Fact]
    public void Internal_manifest_writer_keeps_ascii_sorting_and_python_indentation_rules()
    {
        var value = new JsonObject([new JsonProperty("z", new JsonString("é")), new JsonProperty("a", new JsonArray([JsonNull.Instance, new JsonInteger(0)]))]);
        Assert.Equal("{\n  \"a\": [\n    null,\n    0\n  ],\n  \"z\": \"\\u00e9\"\n}", JsonWriter.WriteManifest(value));
        Assert.Equal("{\n\"a\": [\nnull,\n0\n],\n\"z\": \"\\u00e9\"\n}", JsonWriter.WriteManifest(value, 0));
        Assert.Equal("{\"a\": [null, 0], \"z\": \"\\u00e9\"}", JsonWriter.WriteManifest(value, null));
    }
}
