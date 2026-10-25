namespace AnyInfer;

/// <summary>An image supplied inline or by a remote URL.</summary>
/// <remarks>
/// A URL is a reference passed to the provider; the library never fetches it. A target whose known capabilities
/// exclude image input fails the attempt with <see cref="UnsupportedInputException"/> before its provider is called.
/// </remarks>
public sealed record ImagePart : ContentPart
{
    /// <summary>Creates an image from exactly one inline byte source or URL reference.</summary>
    /// <param name="data">The image bytes, copied at construction; <see langword="null"/> when <paramref name="url"/> is given.</param>
    /// <param name="url">A URL the provider can read the image from; <see langword="null"/> when <paramref name="data"/> is given.</param>
    /// <param name="mediaType">The image media type; must start with <c>image/</c>.</param>
    /// <param name="detail">
    /// The provider image-detail preference: <c>auto</c>, <c>low</c>, <c>high</c>, or <see langword="null"/> for the
    /// provider default.
    /// </param>
    /// <exception cref="ArgumentException">
    /// Both or neither of <paramref name="data"/> and <paramref name="url"/> are supplied, <paramref name="mediaType"/>
    /// does not start with <c>image/</c>, or <paramref name="detail"/> is not an accepted value.
    /// </exception>
    public ImagePart(IEnumerable<byte>? data = null, string? url = null, string mediaType = "image/png", string? detail = null)
    {
        if ((data is null) == (url is null)) throw new ArgumentException("ImagePart requires exactly one of data or url.");
        if (!mediaType.StartsWith("image/", StringComparison.Ordinal)) throw new ArgumentException("Image media type must start with image/.", nameof(mediaType));
        if (detail is not null && detail is not ("auto" or "low" or "high")) throw new ArgumentException("Image detail must be auto, low, or high.", nameof(detail));
        Data = RichGenerationSnapshots.Bytes(data);
        Url = url;
        MediaType = mediaType;
        Detail = detail;
    }
    /// <summary>Gets copied inline bytes, or <see langword="null"/> for a URL reference.</summary>
    public IReadOnlyList<byte>? Data { get; }
    /// <summary>Gets the remote URL reference, or <see langword="null"/> for inline data.</summary>
    public string? Url { get; }
    /// <summary>Gets the declared image media type.</summary>
    public string MediaType { get; }
    /// <summary>Gets the optional provider image-detail preference.</summary>
    public string? Detail { get; }
    /// <summary>Returns a description that reports whether inline data or a URL is present without revealing either.</summary>
    /// <returns>A short description containing the media type and presence flags.</returns>
    public override string ToString() => $"ImagePart {{ HasData = {Data is not null}, HasUrl = {Url is not null}, MediaType = {MediaType} }}";
}

/// <summary>A document supplied inline or by a remote URL.</summary>
/// <remarks>
/// A URL is a reference passed to the provider; the library never fetches it, and an adapter that cannot send a
/// document URL rejects it. A target whose known capabilities exclude document input fails the attempt with
/// <see cref="UnsupportedInputException"/> before its provider is called.
/// </remarks>
public sealed record DocumentPart : ContentPart
{
    /// <summary>Creates a document from exactly one inline byte source or URL reference.</summary>
    /// <param name="data">The document bytes, copied at construction; <see langword="null"/> when <paramref name="url"/> is given.</param>
    /// <param name="url">A URL the provider can read the document from; <see langword="null"/> when <paramref name="data"/> is given.</param>
    /// <param name="mediaType">The document media type; must not be empty.</param>
    /// <param name="filename">An optional filename to send with the document.</param>
    /// <exception cref="ArgumentException">
    /// Both or neither of <paramref name="data"/> and <paramref name="url"/> are supplied, or
    /// <paramref name="mediaType"/> is <see langword="null"/> or empty.
    /// </exception>
    public DocumentPart(IEnumerable<byte>? data = null, string? url = null, string mediaType = "application/pdf", string? filename = null)
    {
        if ((data is null) == (url is null)) throw new ArgumentException("DocumentPart requires exactly one of data or url.");
        if (string.IsNullOrEmpty(mediaType)) throw new ArgumentException("Document media type must not be empty.", nameof(mediaType));
        Data = RichGenerationSnapshots.Bytes(data);
        Url = url;
        MediaType = mediaType;
        Filename = filename;
    }
    /// <summary>Gets copied inline bytes, or <see langword="null"/> for a URL reference.</summary>
    public IReadOnlyList<byte>? Data { get; }
    /// <summary>Gets the remote URL reference, or <see langword="null"/> for inline data.</summary>
    public string? Url { get; }
    /// <summary>Gets the declared document media type.</summary>
    public string MediaType { get; }
    /// <summary>Gets the optional document filename.</summary>
    public string? Filename { get; }
    /// <summary>Returns a description that reports which values are present without revealing the data, URL, or filename.</summary>
    /// <returns>A short description containing the media type and presence flags.</returns>
    public override string ToString() => $"DocumentPart {{ HasData = {Data is not null}, HasUrl = {Url is not null}, MediaType = {MediaType}, HasFilename = {Filename is not null} }}";
}

/// <summary>Inline audio input for a multimodal model.</summary>
/// <remarks>
/// A target whose known capabilities exclude audio input fails the attempt with
/// <see cref="UnsupportedInputException"/> before its provider is called.
/// </remarks>
public sealed record AudioPart : ContentPart
{
    /// <summary>Creates an audio input from nonempty inline bytes.</summary>
    /// <param name="data">The audio bytes, copied at construction; must not be empty.</param>
    /// <param name="mediaType">The audio media type; must start with <c>audio/</c>.</param>
    /// <exception cref="ArgumentNullException"><paramref name="data"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">
    /// <paramref name="data"/> is empty, or <paramref name="mediaType"/> does not start with <c>audio/</c>.
    /// </exception>
    public AudioPart(IEnumerable<byte> data, string mediaType = "audio/wav")
    {
        ArgumentNullException.ThrowIfNull(data);
        Data = RichGenerationSnapshots.Bytes(data)!;
        if (Data.Count == 0) throw new ArgumentException("Audio data must not be empty.", nameof(data));
        if (!mediaType.StartsWith("audio/", StringComparison.Ordinal)) throw new ArgumentException("Audio media type must start with audio/.", nameof(mediaType));
        MediaType = mediaType;
    }
    /// <summary>Gets copied nonempty inline audio bytes.</summary>
    public IReadOnlyList<byte> Data { get; }
    /// <summary>Gets the declared audio media type.</summary>
    public string MediaType { get; }
    /// <summary>Returns a description that omits the audio bytes.</summary>
    /// <returns>A short description containing the media type.</returns>
    public override string ToString() => $"AudioPart {{ HasData = true, MediaType = {MediaType} }}";
}

/// <summary>A video supplied inline or by a provider-hosted URI.</summary>
/// <remarks>
/// A URL is a reference passed to the provider; the library never fetches it. A target whose known capabilities
/// exclude video input fails the attempt with <see cref="UnsupportedInputException"/> before its provider is called,
/// and an adapter that cannot send video rejects it.
/// </remarks>
public sealed record VideoPart : ContentPart
{
    /// <summary>Creates a video from exactly one inline byte source or URL reference.</summary>
    /// <param name="data">The video bytes, copied at construction; <see langword="null"/> when <paramref name="url"/> is given.</param>
    /// <param name="url">A URI the provider can read the video from; <see langword="null"/> when <paramref name="data"/> is given.</param>
    /// <param name="mediaType">The video media type; must start with <c>video/</c>.</param>
    /// <param name="startOffsetS">The optional clip start, in seconds from the beginning; must not be negative.</param>
    /// <param name="endOffsetS">
    /// The optional clip end, in seconds from the beginning; must not be negative and, when both offsets are given,
    /// must be greater than <paramref name="startOffsetS"/>.
    /// </param>
    /// <param name="fps">The optional sampling rate, in frames per second; must be positive.</param>
    /// <exception cref="ArgumentException">
    /// Both or neither of <paramref name="data"/> and <paramref name="url"/> are supplied,
    /// <paramref name="mediaType"/> does not start with <c>video/</c>, the offsets do not form a valid window, or
    /// <paramref name="fps"/> is not positive.
    /// </exception>
    public VideoPart(IEnumerable<byte>? data = null, string? url = null, string mediaType = "video/mp4", double? startOffsetS = null, double? endOffsetS = null, double? fps = null)
    {
        if ((data is null) == (url is null)) throw new ArgumentException("VideoPart requires exactly one of data or url.");
        if (!mediaType.StartsWith("video/", StringComparison.Ordinal)) throw new ArgumentException("Video media type must start with video/.", nameof(mediaType));
        if (startOffsetS < 0 || endOffsetS < 0 || (startOffsetS is not null && endOffsetS is not null && endOffsetS <= startOffsetS)) throw new ArgumentException("Video offsets must form a positive non-negative window.");
        if (fps <= 0) throw new ArgumentException("Video fps must be positive.", nameof(fps));
        Data = RichGenerationSnapshots.Bytes(data);
        Url = url;
        MediaType = mediaType;
        StartOffsetS = startOffsetS;
        EndOffsetS = endOffsetS;
        Fps = fps;
    }
    /// <summary>Gets copied inline bytes, or <see langword="null"/> for a URL reference.</summary>
    public IReadOnlyList<byte>? Data { get; }
    /// <summary>Gets the remote URL reference, or <see langword="null"/> for inline data.</summary>
    public string? Url { get; }
    /// <summary>Gets the declared video media type.</summary>
    public string MediaType { get; }
    /// <summary>Gets the optional clip start offset in seconds.</summary>
    public double? StartOffsetS { get; }
    /// <summary>Gets the optional clip end offset in seconds.</summary>
    public double? EndOffsetS { get; }
    /// <summary>Gets the optional sampled frames per second.</summary>
    public double? Fps { get; }
    /// <summary>Returns a description that reports which values are present without revealing the data or URL.</summary>
    /// <returns>A short description containing the media type and presence flags.</returns>
    public override string ToString() => $"VideoPart {{ HasData = {Data is not null}, HasUrl = {Url is not null}, MediaType = {MediaType}, HasOffsets = {StartOffsetS is not null || EndOffsetS is not null}, HasFps = {Fps is not null} }}";
}
