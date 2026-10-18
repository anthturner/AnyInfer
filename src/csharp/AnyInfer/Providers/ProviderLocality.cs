namespace AnyInfer.Providers;

/// <summary>Declares where a provider descriptor normally runs.</summary>
public enum ProviderLocality
{
    /// <summary>Runs at a hosted provider endpoint.</summary>
    Hosted,
    /// <summary>Runs on the local machine unless its endpoint is remote.</summary>
    Local,
    /// <summary>Runs at a remote endpoint.</summary>
    Remote,
}
