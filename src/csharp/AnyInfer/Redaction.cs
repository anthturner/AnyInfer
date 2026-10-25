using System.Text;
using System.Text.Json;
using System.Globalization;

namespace AnyInfer;

/// <summary>Stores process-local secret values and removes their known encodings from diagnostics.</summary>
/// <remarks>
/// Secrets are held in memory only, for the life of the registry; nothing is persisted. All members
/// are thread-safe. Library diagnostics use the process-global <see cref="Redaction.Registry"/>; a
/// separately constructed registry affects only text passed to its own <see cref="Redact"/>.
/// </remarks>
public sealed class RedactionRegistry
{
    private const int MinimumSecretLength = 6;
    private const string Replacement = "[redacted]";
    private readonly object _gate = new();
    private readonly HashSet<string> _rawSecrets = new(StringComparer.Ordinal);
    private readonly HashSet<string> _secrets = new(StringComparer.Ordinal);

    /// <summary>Creates an empty registry that is independent of the process-global <see cref="Redaction.Registry"/>.</summary>
    public RedactionRegistry()
    {
    }

    /// <summary>Registers a secret and its diagnostic encodings when it is long enough to redact safely.</summary>
    /// <remarks>
    /// Besides the raw value, the registry records its JSON string escapes in two styles (the .NET
    /// serializer's and an ASCII-only style that writes every non-ASCII character as <c>\uXXXX</c>), its percent-encoded forms (with <c>%20</c>
    /// and with <c>+</c> for spaces), the standard Base64 of its UTF-8 bytes, the Base64 of
    /// <c>:</c> followed by the secret (an HTTP Basic credential with an empty user name), and unpadded
    /// Base64url. An encoding shorter than six Unicode scalar values is not recorded.
    /// </remarks>
    /// <param name="secret">Secret to register. <see langword="null"/>, empty, or shorter than six Unicode scalar values is ignored, because such short values cannot be removed without damaging ordinary text.</param>
    public void Register(string? secret)
    {
        if (string.IsNullOrEmpty(secret) || ScalarCount(secret) < MinimumSecretLength)
        {
            return;
        }

        lock (_gate)
        {
            _rawSecrets.Add(secret);
            foreach (var value in Encodings(secret))
            {
                if (ScalarCount(value) >= MinimumSecretLength)
                {
                    _secrets.Add(value);
                }
            }
        }
    }

    /// <summary>Returns text with all registered secret spellings replaced by a stable marker.</summary>
    /// <param name="value">Text to redact; <see langword="null"/> is treated as empty.</param>
    /// <returns><paramref name="value"/> with every registered spelling, longest first and matched case-sensitively, replaced by <c>[redacted]</c>; an empty string when <paramref name="value"/> is <see langword="null"/>.</returns>
    public string Redact(string? value)
    {
        if (value is null)
        {
            return string.Empty;
        }

        string[] values;
        lock (_gate)
        {
            values = _secrets.OrderByDescending(static item => item.Length).ThenBy(static item => item, StringComparer.Ordinal).ToArray();
        }

        foreach (var secret in values)
        {
            value = value.Replace(secret, Replacement, StringComparison.Ordinal);
        }

        return value;
    }

    /// <summary>Gets the number of distinct raw secret values registered; derived encodings are not counted.</summary>
    public int Count
    {
        get
        {
            lock (_gate)
            {
                return _rawSecrets.Count;
            }
        }
    }

    /// <summary>Removes all registered secrets from this process-local registry.</summary>
    public void Clear()
    {
        lock (_gate)
        {
            _rawSecrets.Clear();
            _secrets.Clear();
        }
    }

    private static IEnumerable<string> Encodings(string secret)
    {
        var bytes = Encoding.UTF8.GetBytes(secret);
        var base64 = Convert.ToBase64String(bytes);
        var json = JsonSerializer.Serialize(secret);
        yield return secret;
        yield return PythonJsonEscaped(secret);
        yield return json.Length >= 2 ? json[1..^1] : json;
        yield return Uri.EscapeDataString(secret);
        yield return Uri.EscapeDataString(secret).Replace("%20", "+", StringComparison.Ordinal);
        yield return base64;
        yield return Convert.ToBase64String(Encoding.UTF8.GetBytes($":{secret}"));
        yield return base64.TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }

    private static int ScalarCount(string value) => value.EnumerateRunes().Count();

    private static string PythonJsonEscaped(string value)
    {
        var builder = new StringBuilder();
        foreach (var rune in value.EnumerateRunes())
        {
            switch (rune.Value)
            {
                case (int)'"': builder.Append("\\\""); break;
                case (int)'\\': builder.Append("\\\\"); break;
                case 0x08: builder.Append("\\b"); break;
                case 0x0C: builder.Append("\\f"); break;
                case 0x0A: builder.Append("\\n"); break;
                case 0x0D: builder.Append("\\r"); break;
                case 0x09: builder.Append("\\t"); break;
                default:
                    if (rune.Value <= 0x1F)
                    {
                        AppendEscapedCodeUnit(builder, rune.Value);
                    }
                    else if (rune.Value <= 0x7F)
                    {
                        builder.Append(rune.ToString());
                    }
                    else if (rune.Value <= 0xFFFF)
                    {
                        AppendEscapedCodeUnit(builder, rune.Value);
                    }
                    else
                    {
                        var scalar = rune.Value - 0x10000;
                        AppendEscapedCodeUnit(builder, 0xD800 + (scalar >> 10));
                        AppendEscapedCodeUnit(builder, 0xDC00 + (scalar & 0x3FF));
                    }

                    break;
            }
        }

        return builder.ToString();
    }

    private static void AppendEscapedCodeUnit(StringBuilder builder, int value)
    {
        builder.Append("\\u");
        builder.Append(value.ToString("x4", CultureInfo.InvariantCulture));
    }
}

/// <summary>Provides the process-global redaction registry used by library diagnostics.</summary>
/// <remarks>
/// AnyInfer registers every credential it resolves through a <see cref="Credentials.ResolverChain"/>,
/// plus proxy credentials and a client-certificate password when it creates its own HTTP handler for a
/// provider. Other sensitive values, such as custom header values or option values that are not
/// declared secret fields, are not registered automatically; register them with
/// <see cref="RegisterSecret"/>. Exceptions redact their text when they are constructed, so register a
/// secret before it can reach one.
/// </remarks>
public static class Redaction
{
    /// <summary>Gets the process-global registry.</summary>
    /// <remarks>Calling <see cref="RedactionRegistry.Clear"/> on it stops redaction of every previously registered secret for the whole process.</remarks>
    public static RedactionRegistry Registry { get; } = new();

    /// <summary>Registers a secret before it can be incorporated into diagnostics.</summary>
    /// <param name="secret">Secret to register with <see cref="Registry"/>; <see langword="null"/>, empty, or shorter than six Unicode scalar values is ignored.</param>
    public static void RegisterSecret(string? secret) => Registry.Register(secret);

    /// <summary>Returns text with registered secret spellings removed.</summary>
    /// <param name="value">Text to redact; <see langword="null"/> is treated as empty.</param>
    /// <returns><paramref name="value"/> with every spelling registered in <see cref="Registry"/> replaced by <c>[redacted]</c>; an empty string when <paramref name="value"/> is <see langword="null"/>.</returns>
    public static string Redact(string? value) => Registry.Redact(value);
}
