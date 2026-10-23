using System.Security.Cryptography;
using System.Text;

/// <summary>Rejects a profile publication when default telemetry/manifest serialization leaks planted payload markers.</summary>
internal static class PrivacyPublicationGuard
{
    private static readonly string[] PayloadMarkers = ["answer-marker", "reasoning-marker", "raw-marker"];
    private const string MetadataMarker = "metadata-marker";

    internal static void AssertSafe(string surface, IEnumerable<(string Path, string Value)> leaves)
    {
        ArgumentNullException.ThrowIfNull(surface);
        foreach (var (path, value) in leaves)
        {
            ArgumentNullException.ThrowIfNull(path);
            ArgumentNullException.ThrowIfNull(value);
            if (PayloadMarkers.Any(marker => value.Contains(marker, StringComparison.Ordinal)) ||
                (value.Contains(MetadataMarker, StringComparison.Ordinal) &&
                 !string.Equals(surface, "telemetry:RequestStarted", StringComparison.Ordinal)) ||
                (value.Contains(MetadataMarker, StringComparison.Ordinal) &&
                 !string.Equals(path, "/metadata/fixture", StringComparison.Ordinal)))
            {
                throw new InvalidOperationException($"Refusing to publish {surface}: serialized leaf at {path} leaks a planted privacy marker.");
            }
        }
    }

    internal static (string Path, int Utf8Length, string Sha256) Evidence(string path, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        return (path, bytes.Length, Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
    }

    internal static string Pointer(string parent, string segment) =>
        parent + "/" + segment.Replace("~", "~0", StringComparison.Ordinal).Replace("/", "~1", StringComparison.Ordinal);
}
