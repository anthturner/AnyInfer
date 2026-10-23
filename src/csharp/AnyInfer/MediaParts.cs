namespace AnyInfer;

/// <summary>An image supplied inline or by a remote URL.</summary>
public sealed record ImagePart : ContentPart
{
    /// <summary>Creates an image from exactly one inline byte source or URL reference.</summary>
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
    public override string ToString() => $"ImagePart {{ HasData = {Data is not null}, HasUrl = {Url is not null}, MediaType = {MediaType} }}";
}

/// <summary>A document supplied inline or by a remote URL.</summary>
public sealed record DocumentPart : ContentPart
{
    /// <summary>Creates a document from exactly one inline byte source or URL reference.</summary>
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
    public override string ToString() => $"DocumentPart {{ HasData = {Data is not null}, HasUrl = {Url is not null}, MediaType = {MediaType}, HasFilename = {Filename is not null} }}";
}

/// <summary>Inline audio input for a multimodal model.</summary>
public sealed record AudioPart : ContentPart
{
    /// <summary>Creates an audio input from nonempty inline bytes.</summary>
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
    public override string ToString() => $"AudioPart {{ HasData = true, MediaType = {MediaType} }}";
}

/// <summary>A video supplied inline or by a provider-hosted URI.</summary>
public sealed record VideoPart : ContentPart
{
    /// <summary>Creates a video from exactly one inline byte source or URL reference.</summary>
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
    public override string ToString() => $"VideoPart {{ HasData = {Data is not null}, HasUrl = {Url is not null}, MediaType = {MediaType}, HasOffsets = {StartOffsetS is not null || EndOffsetS is not null}, HasFps = {Fps is not null} }}";
}
