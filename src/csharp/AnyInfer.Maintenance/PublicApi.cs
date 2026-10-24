using System.Reflection;
using System.Text.Json;

internal sealed record PublicApiArguments(string Output)
{
    internal static bool IsRequested(string[] args) => args.Length > 0 && args[0] == "--public-api";

    internal static PublicApiArguments Parse(string[] args)
    {
        if (args.Length != 3 || args[0] != "--public-api" || args[1] != "--output" || string.IsNullOrWhiteSpace(args[2]))
            throw new ArgumentException("Usage: AnyInfer.Maintenance --public-api --output OUTPUT_JSON");
        return new PublicApiArguments(args[2]);
    }
}

internal static class PublicApi
{
    internal static async Task WriteAsync(string output)
    {
        var symbols = Symbols().OrderBy(static symbol => symbol, StringComparer.Ordinal).ToArray();
        var json = JsonSerializer.Serialize(symbols);
        await File.WriteAllTextAsync(output, json + "\n");
    }

    internal static IReadOnlyCollection<string> Symbols()
    {
        const BindingFlags flags = BindingFlags.DeclaredOnly | BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static;
        var symbols = new HashSet<string>(StringComparer.Ordinal);
        foreach (var type in typeof(AnyInfer.AsyncClient).Assembly.GetExportedTypes())
        {
            var typeName = type.FullName ?? throw new InvalidOperationException("A public AnyInfer type has no full name.");
            symbols.Add($"T:{typeName}");
            foreach (var method in type.GetMethods(flags).Where(static method => !method.IsSpecialName))
                symbols.Add($"M:{typeName}.{method.Name}");
            foreach (var property in type.GetProperties(flags)) symbols.Add($"P:{typeName}.{property.Name}");
            foreach (var field in type.GetFields(flags)) symbols.Add($"F:{typeName}.{field.Name}");
            foreach (var @event in type.GetEvents(flags)) symbols.Add($"E:{typeName}.{@event.Name}");
        }
        return symbols;
    }
}
