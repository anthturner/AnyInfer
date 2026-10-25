using System.Security.Cryptography;
using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Manifest;

/// <summary>Provides stable format metadata and digest helpers for run manifests.</summary>
public static partial class ManifestUtilities
{
    /// <summary>Gets the current serialized run-manifest format version.</summary>
    public const string Format = "1";

    /// <summary>Computes the stable SHA-256 digest of a schema's manifest-canonical JSON.</summary>
    /// <param name="schema">The schema object, including unknown keywords.</param>
    /// <returns>A lowercase <c>sha256:</c>-prefixed hexadecimal digest.</returns>
    /// <remarks>
    /// The canonical form sorts keys by Unicode code point, escapes non-ASCII characters and uses
    /// no whitespace, so property order does not affect the digest.
    /// </remarks>
    /// <exception cref="ArgumentNullException"><paramref name="schema"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException">The schema contains a string with an unpaired UTF-16 surrogate.</exception>
    public static string SchemaDigest(JsonObject schema)
    {
        ArgumentNullException.ThrowIfNull(schema);
        return SchemaDigestValue(schema);
    }

    internal static string SchemaDigestValue(JsonValue schema)
    {
        ArgumentNullException.ThrowIfNull(schema);
        var canonical = JsonWriter.WriteManifestCanonical(schema);
        return "sha256:" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
    }
}
