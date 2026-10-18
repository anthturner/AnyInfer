using System.Reflection;

namespace AnyInfer.Internal;

/// <summary>Reads the assembly version once for request-scoped diagnostic snapshots.</summary>
internal static class AnyInferVersion
{
    internal static string Value { get; } =
        typeof(AnyInferVersion).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
        ?? typeof(AnyInferVersion).Assembly.GetName().Version?.ToString()
        ?? "unknown";
}
