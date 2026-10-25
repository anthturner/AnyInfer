using System.Reflection;

namespace AnyInfer.Examples.Cases;

/// <summary>Marks a static method the offline example runner executes and asserts.</summary>
/// <remarks>
/// A case method takes no parameters and returns <see cref="Task"/> or nothing. Each published
/// recipe that is not verified directly by <c>Program.cs</c> has a case, so the documentation
/// can include the recipe's source knowing the runner executes it offline.
/// </remarks>
[AttributeUsage(AttributeTargets.Method, AllowMultiple = false)]
internal sealed class ExampleCaseAttribute(string name) : Attribute
{
    /// <summary>Gets the case name the runner reports.</summary>
    public string Name { get; } = name;
}

/// <summary>Discovers and runs every <see cref="ExampleCaseAttribute"/> case in this project.</summary>
internal static class ExampleCases
{
    /// <summary>Runs every case in name order, failing on the first case that throws.</summary>
    internal static async Task RunAllAsync()
    {
        const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
        var cases = typeof(ExampleCases).Assembly.GetTypes()
            .SelectMany(static type => type.GetMethods(flags))
            .Select(static method => (Method: method, Case: method.GetCustomAttribute<ExampleCaseAttribute>()))
            .Where(static item => item.Case is not null)
            .OrderBy(static item => item.Case!.Name, StringComparer.Ordinal)
            .ToArray();
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (method, attribute) in cases)
        {
            if (!names.Add(attribute!.Name)) throw new InvalidOperationException($"Duplicate example case {attribute.Name}.");
            if (method.GetParameters().Length != 0)
                throw new InvalidOperationException($"Example case {attribute.Name} must not take parameters.");
            var result = method.Invoke(null, null);
            if (result is Task task) await task.ConfigureAwait(false);
            Console.WriteLine($"example case {attribute.Name}: ok");
        }
    }
}

/// <summary>Shared offline helpers for example cases.</summary>
internal static class ExampleSupport
{
    /// <summary>The offline OpenAI-compatible endpoint scripted handlers answer for.</summary>
    internal const string BaseUrl = "https://offline.example/v1";

    /// <summary>The OpenAI-compatible target the scripted handlers accept.</summary>
    internal const string Target = "openai-compat:demo";

    /// <summary>Throws when an example's observable result is not the documented one.</summary>
    internal static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    /// <summary>Returns a copy of provider settings that sends HTTP through a scripted handler.</summary>
    internal static ProviderSettings WithTransport(ProviderSettings source, HttpMessageHandler transport) =>
        ProviderSettings.Of(
            source.ProviderId,
            source.BaseUrl,
            source.ApiKey,
            source.ApiVersion,
            source.Headers,
            source.Options,
            source.TimeoutS,
            transport,
            source.Alias,
            source.Limits,
            source.Proxy,
            source.Verify,
            source.ClientCertificate);
}
