using System.Numerics;
using AnyInfer.Json;
using Xunit;

namespace AnyInfer.Tests;

public sealed class JsonValueTests
{
    [Fact]
    public void Reader_keeps_first_duplicate_position_and_last_value()
    {
        var value = Assert.IsType<JsonObject>(JsonReader.Read("{\"first\":1,\"later\":2,\"first\":3}"));

        Assert.Collection(value.Properties,
            property => Assert.Equal(("first", new JsonInteger(3)), (property.Name, property.Value)),
            property => Assert.Equal(("later", new JsonInteger(2)), (property.Name, property.Value)));
        Assert.Equal("{\"first\":3,\"later\":2}", JsonWriter.Write(value));
    }

    [Theory]
    [InlineData("-9223372036854775808")]
    [InlineData("9223372036854775808")]
    public void Reader_preserves_portable_integer_endpoints(string source)
    {
        var value = Assert.IsType<JsonInteger>(JsonReader.Read(source));

        Assert.Equal(BigInteger.Parse(source), value.Value);
        Assert.Equal(source, JsonWriter.Write(value));
    }

    [Fact]
    public void Reader_rejects_integer_just_outside_portable_range()
    {
        Assert.Throws<FormatException>(() => JsonReader.Read("9223372036854775809"));
        Assert.Throws<FormatException>(() => JsonReader.Read("-9223372036854775809"));
    }

    [Fact]
    public void Reader_preserves_large_integer_without_binary64_narrowing()
    {
        var value = Assert.IsType<JsonInteger>(JsonReader.Read("9007199254740993"));

        Assert.Equal(new BigInteger(9007199254740993), value.Value);
    }

    [Fact]
    public void Equality_distinguishes_json_types_and_signed_zero_but_schema_controls_do_not()
    {
        var integer = new JsonInteger(1);
        var number = new JsonNumber(1.0, "1.0");
        var positiveZero = new JsonNumber(0.0, "0.0");
        var negativeZero = new JsonNumber(-0.0, "-0.0");

        Assert.False(JsonEquality.TypeAwareEquals(integer, number));
        Assert.False(JsonEquality.TypeAwareEquals(positiveZero, negativeZero));
        Assert.True(JsonEquality.SchemaEquals(integer, number));
        Assert.True(JsonEquality.NumericControlEquals(positiveZero, negativeZero));
        Assert.False(JsonEquality.SchemaEquals(new JsonBoolean(true), integer));
        Assert.False(JsonEquality.SchemaEquals(JsonNull.Instance, integer));
    }

    [Fact]
    public void Objects_ignore_member_order_for_equality_and_arrays_do_not()
    {
        var first = JsonReader.Read("{\"a\":[1,2],\"b\":true}");
        var reordered = JsonReader.Read("{\"b\":true,\"a\":[1,2]}");
        var changedArray = JsonReader.Read("{\"b\":true,\"a\":[2,1]}");

        Assert.True(JsonEquality.TypeAwareEquals(first, reordered));
        Assert.False(JsonEquality.TypeAwareEquals(first, changedArray));
    }

    [Fact]
    public void Codepoint_order_compares_non_bmp_values_without_utf16_ordinal_shortcuts()
    {
        Assert.True(JsonEquality.CompareCodePoints("\U0001f600", "\uffff") > 0);
        Assert.True(JsonEquality.CompareCodePoints("a", "\U0001f600") < 0);
    }

    [Theory]
    [InlineData("\"\\uD800\"")]
    [InlineData("\"\\uDC00\"")]
    [InlineData("NaN")]
    [InlineData("1e9999")]
    [InlineData("true false")]
    public void Reader_rejects_nonordinary_or_trailing_input(string source)
    {
        Assert.Throws<FormatException>(() => JsonReader.Read(source));
    }

    [Fact]
    public void Reader_accepts_raw_utf8_and_escaped_surrogate_pair_but_keeps_reserved_keys_literal()
    {
        var raw = Assert.IsType<JsonObject>(JsonReader.Read("{\"emoji\":\"😀\",\"$schema_prompt\":true}"));
        var escaped = Assert.IsType<JsonString>(JsonReader.Read("\"\\uD83D\\uDE00\""));

        Assert.True(raw.TryGetValue("$schema_prompt", out var reserved));
        Assert.Equal(new JsonBoolean(true), reserved);
        Assert.Equal("😀", escaped.Value);
    }

    [Fact]
    public void Reader_does_not_treat_literal_unicode_escape_text_as_a_surrogate_escape()
    {
        const string slash = "\\";
        const string quote = "\"";
        var literalSource = quote + slash + slash + "uD800 " + slash + slash + "uDC00 " + slash + slash + slash + quote + " " + slash + slash + "/" + quote;
        var literal = Assert.IsType<JsonString>(JsonReader.Read(literalSource));
        var objectValue = Assert.IsType<JsonObject>(JsonReader.Read("{\"\\\\uD800\":\"\\\\uDC00\"}"));
        var paired = Assert.IsType<JsonString>(JsonReader.Read("\"\\uD83D\\uDE00\""));

        Assert.Equal(slash + "uD800 " + slash + "uDC00 " + slash + quote + " " + slash + "/", literal.Value);
        Assert.True(objectValue.TryGetValue("\\uD800", out var property));
        Assert.Equal(new JsonString("\\uDC00"), property);
        Assert.Equal("😀", paired.Value);
    }

    [Fact]
    public void Reader_rejects_malformed_utf8_in_values_and_property_names()
    {
        var overlongValue = new byte[] { (byte)'"', 0xc0, 0x80, (byte)'"' };
        var surrogateValue = new byte[] { (byte)'"', 0xed, 0xa0, 0x80, (byte)'"' };
        var overlongKey = new byte[] { (byte)'{', (byte)'"', 0xc0, 0x80, (byte)'"', (byte)':', (byte)'1', (byte)'}' };
        var surrogateKey = new byte[] { (byte)'{', (byte)'"', 0xed, 0xa0, 0x80, (byte)'"', (byte)':', (byte)'1', (byte)'}' };

        Assert.Throws<FormatException>(() => JsonReader.Read(overlongValue));
        Assert.Throws<FormatException>(() => JsonReader.Read(surrogateValue));
        Assert.Throws<FormatException>(() => JsonReader.Read(overlongKey));
        Assert.Throws<FormatException>(() => JsonReader.Read(surrogateKey));
    }

    [Fact]
    public void Reader_rejects_actual_unpaired_utf16_surrogates_at_string_entry()
    {
        Assert.Throws<FormatException>(() => JsonReader.Read("\"\uD800\""));
        Assert.Throws<FormatException>(() => JsonReader.Read("\"\uDC00\""));
    }

    [Fact]
    public void Writers_preserve_compact_order_and_render_canonical_schema_json()
    {
        var value = new JsonObject([
            new JsonProperty("\U0001f600", new JsonString("é")),
            new JsonProperty("a", new JsonArray([new JsonNumber(-0.0, "-0.0"), new JsonNumber(1.0, "1.0")])),
        ]);

        Assert.Equal("{\"😀\":\"é\",\"a\":[-0.0,1.0]}", JsonWriter.Write(value));
        Assert.Equal("{\n  \"a\": [\n    -0.0,\n    1.0\n  ],\n  \"\\ud83d\\ude00\": \"\\u00e9\"\n}", JsonWriter.WriteCanonical(value));
    }

    [Fact]
    public void Writer_rejects_unpaired_surrogate_and_unverified_number_lexeme()
    {
        Assert.Throws<ArgumentException>(() => JsonWriter.Write(new JsonString("\uD800")));
        Assert.Equal("1.0", JsonWriter.Write(new JsonNumber(1.0, "1e9999")));
    }

    [Fact]
    public void Writer_keeps_numbers_as_binary64_when_metadata_uses_an_integer_lexeme()
    {
        var integral = Assert.IsType<JsonNumber>(JsonReader.Read(JsonWriter.Write(new JsonNumber(1.0, "1"))));
        var negativeZero = Assert.IsType<JsonNumber>(JsonReader.Read(JsonWriter.Write(new JsonNumber(-0.0, "-0"))));
        var decimalValue = new JsonNumber(1.25, "1.25");
        var exponentValue = new JsonNumber(1e20, "1e+20");

        Assert.Equal(1.0, integral.Value);
        Assert.True(negativeZero.IsNegativeZero);
        Assert.Equal("1.25", JsonWriter.Write(decimalValue));
        Assert.Equal("1e+20", JsonWriter.Write(exponentValue));
    }
}
