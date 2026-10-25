using System.Text;

namespace AnyInfer;

/// <summary>A provider-run capability requested for one generation.</summary>
/// <remarks>
/// A target whose provider has no wire form for the kind, or whose known capabilities exclude it, fails the attempt
/// with <see cref="UnsupportedInputException"/> before its provider is called.
/// </remarks>
public sealed record ServerToolSpec
{
    /// <summary>Creates a provider-run capability declaration.</summary>
    /// <param name="kind">The capability: <c>web_search</c> or <c>code_execution</c>.</param>
    /// <param name="maxUses">
    /// The most invocations the provider may make, or <see langword="null"/> for the provider default; must be at
    /// least <c>1</c>.
    /// </param>
    /// <exception cref="ArgumentException"><paramref name="kind"/> is not a known server tool kind.</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="maxUses"/> is less than <c>1</c>.</exception>
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
    /// <param name="kind">The normalized provider-run tool kind, such as <c>web_search</c>.</param>
    /// <param name="uses">The provider-reported number of invocations.</param>
    /// <exception cref="ArgumentNullException"><paramref name="kind"/> is <see langword="null"/>.</exception>
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
/// <remarks>
/// Every field is optional because providers report different subsets. An absent offset means the provider did not
/// locate the citation in the answer; it is not the same as offset <c>0</c>.
/// </remarks>
public sealed record Citation
{
    /// <summary>Creates a provider-reported source citation.</summary>
    /// <param name="startIndex">
    /// The inclusive Unicode scalar offset into the answer text where the supported span begins, or
    /// <see langword="null"/> when the provider did not report one.
    /// </param>
    /// <param name="endIndex">
    /// The exclusive Unicode scalar offset into the answer text where the supported span ends, or
    /// <see langword="null"/> when the provider did not report one.
    /// </param>
    /// <param name="quotedText">The quoted source passage; empty when the provider reported only a location.</param>
    /// <param name="documentIndex">
    /// The position of the cited document among the documents supplied in the request, or <see langword="null"/> for a
    /// source that was not part of the request.
    /// </param>
    /// <param name="title">The source title; empty when the provider reported none.</param>
    /// <param name="uri">The source URI; empty when the provider reported none. The library never fetches it.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="quotedText"/>, <paramref name="title"/>, or <paramref name="uri"/> is <see langword="null"/>.
    /// </exception>
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
    /// <param name="text">The answer text the offsets refer to, normally <see cref="Generation.Text"/>.</param>
    /// <returns>
    /// The cited substring of <paramref name="text"/>, or an empty string when either offset is
    /// <see langword="null"/> or the clamped span is empty.
    /// </returns>
    /// <exception cref="ArgumentNullException"><paramref name="text"/> is <see langword="null"/>.</exception>
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
    /// <param name="token">The generated token as the provider spells it.</param>
    /// <param name="logprob">The token's natural-log probability.</param>
    /// <param name="top">
    /// The most likely alternative tokens at this position, in provider order; <see langword="null"/> means none.
    /// Copied.
    /// </param>
    /// <param name="bytes">The token's raw UTF-8 bytes, or <see langword="null"/> when not reported. Copied.</param>
    /// <exception cref="ArgumentNullException"><paramref name="token"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="top"/> contains a <see langword="null"/> element.</exception>
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
    /// <param name="url">The source URL; empty when the provider reported none. The library never fetches it.</param>
    /// <param name="title">The source title; empty when the provider reported none.</param>
    /// <exception cref="ArgumentNullException">
    /// <paramref name="url"/> or <paramref name="title"/> is <see langword="null"/>.
    /// </exception>
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
