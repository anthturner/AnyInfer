using System.Text;

namespace AnyInfer;

/// <summary>A provider-run capability requested for one generation.</summary>
public sealed record ServerToolSpec
{
    /// <summary>Creates a provider-run capability declaration.</summary>
    public ServerToolSpec(string kind, int? maxUses = null)
    {
        if (kind is not ("web_search" or "code_execution")) throw new ArgumentException("Unknown server tool kind.", nameof(kind));
        if (maxUses is < 1) throw new ArgumentOutOfRangeException(nameof(maxUses));
        Kind = kind; MaxUses = maxUses;
    }
    /// <summary>Gets the normalized provider-run tool kind.</summary>
    public string Kind { get; }
    /// <summary>Gets the optional invocation ceiling.</summary>
    public int? MaxUses { get; }
}

/// <summary>The count of provider-run tool invocations in a generation.</summary>
public sealed record ServerToolUse
{
    /// <summary>Creates a provider-run tool-use count.</summary>
    public ServerToolUse(string kind, long uses)
    {
        Kind = kind ?? throw new ArgumentNullException(nameof(kind));
        Uses = uses;
    }

    /// <summary>Gets the normalized provider-run tool kind.</summary>
    public string Kind { get; }
    /// <summary>Gets the provider-reported invocation count.</summary>
    public long Uses { get; }
}

/// <summary>A source citation supplied by a provider.</summary>
public sealed record Citation
{
    /// <summary>Creates a provider-reported source citation.</summary>
    public Citation(int? startIndex = null, int? endIndex = null, string quotedText = "", int? documentIndex = null, string title = "", string uri = "")
    {
        StartIndex = startIndex;
        EndIndex = endIndex;
        QuotedText = quotedText ?? throw new ArgumentNullException(nameof(quotedText));
        DocumentIndex = documentIndex;
        Title = title ?? throw new ArgumentNullException(nameof(title));
        Uri = uri ?? throw new ArgumentNullException(nameof(uri));
    }
    /// <summary>Gets the optional inclusive scalar offset into answer text.</summary>
    public int? StartIndex { get; }
    /// <summary>Gets the optional exclusive scalar offset into answer text.</summary>
    public int? EndIndex { get; }
    /// <summary>Gets provider-reported quoted source text.</summary>
    public string QuotedText { get; }
    /// <summary>Gets the optional ordinal of a supplied source document.</summary>
    public int? DocumentIndex { get; }
    /// <summary>Gets provider-reported source title.</summary>
    public string Title { get; }
    /// <summary>Gets provider-reported source URI.</summary>
    public string Uri { get; }
    /// <summary>Gets the cited answer span using Unicode scalar positions, clamped to the answer bounds.</summary>
    public string SpanOf(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        if (StartIndex is null || EndIndex is null) return "";
        var count = text.EnumerateRunes().Count();
        var start = Math.Clamp(StartIndex.Value, 0, count);
        var end = Math.Clamp(EndIndex.Value, start, count);
        return text[ScalarOffset(text, start)..ScalarOffset(text, end)];
    }
    private static int ScalarOffset(string text, int scalarIndex)
    {
        var offset = 0; var index = 0;
        foreach (var rune in text.EnumerateRunes()) { if (index++ == scalarIndex) return offset; offset += rune.Utf16SequenceLength; }
        return text.Length;
    }
}

/// <summary>A generated token and its natural-log probability.</summary>
public sealed record TokenLogprob
{
    /// <summary>Creates a token log-probability with optional alternatives and raw bytes.</summary>
    public TokenLogprob(string token, double logprob, IEnumerable<TokenLogprob>? top = null, IEnumerable<byte>? bytes = null)
    {
        Token = token ?? throw new ArgumentNullException(nameof(token));
        Logprob = logprob;
        Top = RichGenerationSnapshots.List(top, nameof(top));
        Bytes = RichGenerationSnapshots.Bytes(bytes);
    }
    /// <summary>Gets the provider-spelled generated token.</summary>
    public string Token { get; }
    /// <summary>Gets the token natural-log probability.</summary>
    public double Logprob { get; }
    /// <summary>Gets copied alternative tokens in provider-reported order.</summary>
    public IReadOnlyList<TokenLogprob> Top { get; }
    /// <summary>Gets copied raw token UTF-8 bytes, when reported.</summary>
    public IReadOnlyList<byte>? Bytes { get; }
    /// <summary>Gets the probability corresponding to <see cref="Logprob"/>.</summary>
    public double Probability => Math.Exp(Logprob);
}

/// <summary>A source reported by a provider-run tool.</summary>
public sealed record ServerToolSource
{
    /// <summary>Creates a provider-reported server-tool source.</summary>
    public ServerToolSource(string url = "", string title = "")
    {
        Url = url ?? throw new ArgumentNullException(nameof(url));
        Title = title ?? throw new ArgumentNullException(nameof(title));
    }

    /// <summary>Gets the provider-reported source URL.</summary>
    public string Url { get; }
    /// <summary>Gets the provider-reported source title.</summary>
    public string Title { get; }
}
