using System.Net;

namespace AnyInfer;

/// <summary>Immutable explicit HTTP(S) proxy settings for one provider instance.</summary>
public sealed record ProviderProxy
{
    /// <summary>Initializes proxy settings with an address that contains no userinfo.</summary>
    public ProviderProxy(Uri address, string? userName = null, string? password = null)
    {
        ValidateAddress(address, nameof(address));
        if (!string.IsNullOrEmpty(address.UserInfo))
        {
            throw new ArgumentException("The proxy address must not contain userinfo.", nameof(address));
        }

        Address = address;
        UserName = userName;
        Password = password;
        ConfigurationValue = BuildConfigurationValue(address, userName, password);
    }

    private ProviderProxy(Uri address, string? userName, string? password, string configurationValue)
    {
        Address = address;
        UserName = userName;
        Password = password;
        ConfigurationValue = configurationValue;
    }

    /// <summary>Gets the userinfo-free HTTP(S) proxy address.</summary>
    public Uri Address { get; }

    /// <summary>Gets the optional literal proxy user name; do not log this value.</summary>
    public string? UserName { get; }

    /// <summary>Gets the optional literal proxy password; do not log this value.</summary>
    public string? Password { get; }

    /// <summary>Parses one literal HTTP(S) proxy URI without exposing it in diagnostics.</summary>
    public static ProviderProxy Parse(string value)
    {
        if (string.IsNullOrWhiteSpace(value)
            || !Uri.TryCreate(value.Trim(), UriKind.Absolute, out var parsed))
        {
            throw new ArgumentException("The proxy must be an absolute HTTP(S) URI.", nameof(value));
        }

        ValidateAddress(parsed, nameof(value));
        var userName = default(string);
        var password = default(string);
        if (!string.IsNullOrEmpty(parsed.UserInfo))
        {
            var separator = parsed.UserInfo.IndexOf(':');
            userName = Uri.UnescapeDataString(separator < 0 ? parsed.UserInfo : parsed.UserInfo[..separator]);
            password = separator < 0 ? null : Uri.UnescapeDataString(parsed.UserInfo[(separator + 1)..]);
        }

        var builder = new UriBuilder(parsed) { UserName = string.Empty, Password = string.Empty };
        return new ProviderProxy(builder.Uri, userName, password, value.Trim());
    }

    /// <summary>Returns an identity-only representation that omits the proxy address and credentials.</summary>
    public override string ToString() => "ProviderProxy";

    internal string ConfigurationValue { get; }

    private static void ValidateAddress(Uri address, string parameterName)
    {
        ArgumentNullException.ThrowIfNull(address);
        if (!address.IsAbsoluteUri
            || address.Scheme is not ("http" or "https")
            || string.IsNullOrEmpty(address.Host)
            || !string.IsNullOrEmpty(address.Query)
            || !string.IsNullOrEmpty(address.Fragment)
            || (address.AbsolutePath is not "" and not "/"))
        {
            throw new ArgumentException("The proxy must be an absolute HTTP(S) URI without query, fragment, or path.", parameterName);
        }
    }

    private static string BuildConfigurationValue(Uri address, string? userName, string? password)
    {
        if (userName is null && password is null)
        {
            return address.OriginalString;
        }

        var builder = new UriBuilder(address)
        {
            UserName = userName ?? string.Empty,
            Password = password ?? string.Empty,
        };
        return builder.Uri.OriginalString;
    }
}
