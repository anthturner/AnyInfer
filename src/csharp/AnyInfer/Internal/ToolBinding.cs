using System.ComponentModel;
using System.Numerics;
using System.Reflection;
using System.Runtime.CompilerServices;
using AnyInfer.Json;

namespace AnyInfer.Internal;

internal static class ToolBinding
{
    internal static Tool Create(Delegate function, string? name, string? description)
    {
        ArgumentNullException.ThrowIfNull(function);
        var method = function.Method;
        if (function.GetInvocationList().Length != 1 || method.ContainsGenericParameters || method.ReturnType == typeof(void) && method.GetCustomAttribute<AsyncStateMachineAttribute>() is not null)
        {
            throw Invalid("The tool delegate must be a single non-generic callable with a supported return type.");
        }

        var parameters = method.GetParameters();
        var declarations = new List<(ParameterInfo Parameter, Type Type)>();
        var injectCancellation = false;
        var finalParams = false;
        for (var index = 0; index < parameters.Length; index++)
        {
            var parameter = parameters[index];
            if (parameter.ParameterType.IsByRef || parameter.IsOut || parameter.ParameterType.IsPointer)
            {
                throw Invalid($"Tool parameter '{parameter.Name}' is not supported.");
            }
            if (parameter.ParameterType == typeof(CancellationToken))
            {
                if (parameters.Count(static parameter => parameter.ParameterType == typeof(CancellationToken)) != 1)
                    throw Invalid("A tool may declare at most one CancellationToken parameter.");
                injectCancellation = true;
                continue;
            }
            if (parameter.GetCustomAttribute<ParamArrayAttribute>() is not null)
            {
                if (index != parameters.Length - 1 || !parameter.ParameterType.IsArray || !Supported(parameter.ParameterType.GetElementType()!))
                    throw Invalid($"Tool params parameter '{parameter.Name}' is not supported.");
                finalParams = true;
                continue;
            }
            if (!Supported(parameter.ParameterType)) throw Invalid($"Tool parameter '{parameter.Name}' has an unsupported CLR type.");
            declarations.Add((parameter, parameter.ParameterType));
        }
        if (!SupportedReturn(method.ReturnType)) throw Invalid("The tool return type is not supported.");

        var toolName = name ?? method.Name;
        if (string.IsNullOrWhiteSpace(toolName)) throw Invalid("Tool names cannot be empty.");
        var summary = description ?? method.GetCustomAttribute<DescriptionAttribute>()?.Description ?? string.Empty;
        var properties = new List<JsonProperty>();
        var required = new List<JsonValue>();
        foreach (var declaration in declarations)
        {
            properties.Add(new JsonProperty(declaration.Parameter.Name!, Schema(declaration.Type)));
            if (!declaration.Parameter.HasDefaultValue) required.Add(new JsonString(declaration.Parameter.Name!));
        }
        var schema = new JsonObject([
            new JsonProperty("type", new JsonString("object")),
            new JsonProperty("properties", new JsonObject(properties)),
            new JsonProperty("required", new JsonArray(required)),
            new JsonProperty("additionalProperties", new JsonBoolean(false)),
        ]);
        var spec = new ToolSpec(toolName, summary, schema);
        return new Tool(spec, (arguments, cancellationToken) => Invoke(function, parameters, declarations, injectCancellation, finalParams, arguments, cancellationToken));
    }

    internal static string RenderReturn(object? value)
    {
        if (value is null) return string.Empty;
        if (value is string text) return text;
        if (TryToJson(value, new HashSet<object>(ReferenceEqualityComparer.Instance), out var json)) return JsonWriter.WriteModern(json);
        return value.ToString() ?? string.Empty;
    }

    private static async ValueTask<object?> Invoke(Delegate function, ParameterInfo[] parameters, List<(ParameterInfo Parameter, Type Type)> declarations, bool injectCancellation, bool finalParams, JsonObject arguments, CancellationToken token)
    {
        var values = new object?[parameters.Length];
        var declaredNames = declarations.Select(static item => item.Parameter.Name!).ToHashSet(StringComparer.Ordinal);
        foreach (var property in arguments.Properties)
            if (!declaredNames.Contains(property.Name)) throw new ArgumentException($"Unknown tool argument '{property.Name}'.");
        foreach (var (parameter, type) in declarations)
        {
            var index = Array.IndexOf(parameters, parameter);
            if (arguments.TryGetValue(parameter.Name!, out var json)) values[index] = FromJson(json, type);
            else if (parameter.HasDefaultValue) values[index] = parameter.DefaultValue;
            else throw new ArgumentException($"Missing required tool argument '{parameter.Name}'.");
        }
        for (var index = 0; index < parameters.Length; index++)
        {
            if (parameters[index].ParameterType == typeof(CancellationToken)) values[index] = token;
            else if (parameters[index].GetCustomAttribute<ParamArrayAttribute>() is not null) values[index] = Array.CreateInstance(parameters[index].ParameterType.GetElementType()!, 0);
        }
        object? result;
        try { result = function.DynamicInvoke(values); }
        catch (TargetInvocationException exception) when (exception.InnerException is not null) { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(exception.InnerException).Throw(); throw; }
        return await Await(result).ConfigureAwait(false);
    }

    private static async ValueTask<object?> Await(object? result)
    {
        if (result is Task task) { await task.ConfigureAwait(false); return task.GetType().IsGenericType ? task.GetType().GetProperty("Result")!.GetValue(task) : null; }
        if (result is ValueTask valueTask) { await valueTask.ConfigureAwait(false); return null; }
        if (result is not null && result.GetType().IsGenericType && result.GetType().GetGenericTypeDefinition() == typeof(ValueTask<>))
        {
            var valueTaskAsTask = (Task)result.GetType().GetMethod("AsTask")!.Invoke(result, null)!;
            await valueTaskAsTask.ConfigureAwait(false);
            return valueTaskAsTask.GetType().GetProperty("Result")!.GetValue(valueTaskAsTask);
        }
        return result;
    }

    private static bool SupportedReturn(Type type) => !type.IsByRef && !type.IsPointer;
    private static bool Supported(Type type)
    {
        type = Nullable.GetUnderlyingType(type) ?? type;
        if (type == typeof(string) || type == typeof(bool) || type == typeof(int) || type == typeof(long) || type == typeof(BigInteger) || type == typeof(double) || type == typeof(JsonValue) || type == typeof(JsonObject) || type == typeof(JsonArray) || type == typeof(object)) return true;
        if (type.IsArray) return type.GetArrayRank() == 1 && Supported(type.GetElementType()!);
        if (type.IsGenericType)
        {
            var definition = type.GetGenericTypeDefinition(); var arguments = type.GetGenericArguments();
            return (definition == typeof(List<>) || definition == typeof(IReadOnlyList<>)) && Supported(arguments[0]) ||
                (definition == typeof(Dictionary<,>) || definition == typeof(IReadOnlyDictionary<,>)) && arguments[0] == typeof(string) && Supported(arguments[1]);
        }
        return false;
    }

    private static JsonValue Schema(Type type)
    {
        type = Nullable.GetUnderlyingType(type) ?? type;
        if (type == typeof(string)) return TypeSchema("string");
        if (type == typeof(bool)) return TypeSchema("boolean");
        if (type == typeof(int) || type == typeof(long) || type == typeof(BigInteger)) return TypeSchema("integer");
        if (type == typeof(double)) return TypeSchema("number");
        if (type == typeof(JsonObject) || type.IsGenericType && (type.GetGenericTypeDefinition() == typeof(Dictionary<,>) || type.GetGenericTypeDefinition() == typeof(IReadOnlyDictionary<,>))) return TypeSchema("object");
        if (type == typeof(JsonArray) || type.IsArray || type.IsGenericType && (type.GetGenericTypeDefinition() == typeof(List<>) || type.GetGenericTypeDefinition() == typeof(IReadOnlyList<>))) return TypeSchema("array");
        return new JsonObject([]);
    }
    private static JsonObject TypeSchema(string type) => new([new JsonProperty("type", new JsonString(type))]);

    private static object? FromJson(JsonValue json, Type target)
    {
        var nullable = Nullable.GetUnderlyingType(target); if (json is JsonNull) { if (!target.IsValueType || nullable is not null) return null; throw new ArgumentException("Null is not valid for this tool parameter."); }
        var type = nullable ?? target;
        if (type == typeof(object) || type == typeof(JsonValue)) return json;
        if (type == typeof(JsonObject)) return json as JsonObject ?? throw new ArgumentException("Expected a JSON object.");
        if (type == typeof(JsonArray)) return json as JsonArray ?? throw new ArgumentException("Expected a JSON array.");
        if (type == typeof(string)) return (json as JsonString)?.Value ?? throw new ArgumentException("Expected a JSON string.");
        if (type == typeof(bool)) return (json as JsonBoolean)?.Value ?? throw new ArgumentException("Expected a JSON boolean.");
        if (type == typeof(BigInteger)) return (json as JsonInteger)?.Value ?? throw new ArgumentException("Expected a JSON integer.");
        if (type == typeof(int)) { var value = (json as JsonInteger)?.Value ?? throw new ArgumentException("Expected a JSON integer."); return value >= int.MinValue && value <= int.MaxValue ? (int)value : throw new ArgumentException("JSON integer is outside Int32 range."); }
        if (type == typeof(long)) { var value = (json as JsonInteger)?.Value ?? throw new ArgumentException("Expected a JSON integer."); return value >= long.MinValue && value <= long.MaxValue ? (long)value : throw new ArgumentException("JSON integer is outside Int64 range."); }
        if (type == typeof(double)) return json is JsonNumber number ? number.Value : json is JsonInteger integer ? checked((double)integer.Value) : throw new ArgumentException("Expected a JSON number.");
        if (type.IsArray) { var array = json as JsonArray ?? throw new ArgumentException("Expected a JSON array."); var item = type.GetElementType()!; var result = Array.CreateInstance(item, array.Items.Count); for (var index = 0; index < array.Items.Count; index++) result.SetValue(FromJson(array.Items[index], item), index); return result; }
        if (type.IsGenericType && (type.GetGenericTypeDefinition() == typeof(List<>) || type.GetGenericTypeDefinition() == typeof(IReadOnlyList<>))) { var array = json as JsonArray ?? throw new ArgumentException("Expected a JSON array."); var item = type.GetGenericArguments()[0]; var list = (System.Collections.IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(item))!; foreach (var value in array.Items) list.Add(FromJson(value, item)); return list; }
        if (type.IsGenericType && (type.GetGenericTypeDefinition() == typeof(Dictionary<,>) || type.GetGenericTypeDefinition() == typeof(IReadOnlyDictionary<,>))) { var obj = json as JsonObject ?? throw new ArgumentException("Expected a JSON object."); var valueType = type.GetGenericArguments()[1]; var dictionary = (System.Collections.IDictionary)Activator.CreateInstance(typeof(Dictionary<,>).MakeGenericType(typeof(string), valueType))!; foreach (var property in obj.Properties) dictionary.Add(property.Name, FromJson(property.Value, valueType)); return dictionary; }
        throw new ArgumentException("Unsupported tool parameter type.");
    }

    private static bool TryToJson(object value, HashSet<object> seen, out JsonValue json)
    {
        switch (value)
        {
            case JsonValue tagged: json = tagged; return true;
            case bool boolean: json = new JsonBoolean(boolean); return true;
            case string text: json = new JsonString(text); return true;
            case BigInteger integer: json = new JsonInteger(integer); return true;
            case ulong unsigned: json = new JsonInteger(new BigInteger(unsigned)); return true;
            case byte or sbyte or short or ushort or int or uint or long: json = new JsonInteger(new BigInteger(Convert.ToInt64(value, System.Globalization.CultureInfo.InvariantCulture))); return true;
            case float single when float.IsFinite(single): json = new JsonNumber(single); return true;
            case double number when double.IsFinite(number): json = new JsonNumber(number); return true;
            case System.Collections.IDictionary dictionary:
                if (!seen.Add(value)) throw new InvalidOperationException("Cyclic tool return value.");
                var properties = new List<JsonProperty>();
                foreach (System.Collections.DictionaryEntry entry in dictionary)
                {
                    if (entry.Key is not string name)
                    {
                        seen.Remove(value); json = null!; return false;
                    }
                    JsonValue child;
                    if (entry.Value is null) child = JsonNull.Instance;
                    else if (!TryToJson(entry.Value, seen, out child))
                    {
                        seen.Remove(value); json = null!; return false;
                    }
                    properties.Add(new JsonProperty(name, child));
                }
                seen.Remove(value); json = new JsonObject(properties); return true;
            case System.Collections.IEnumerable enumerable:
                if (!seen.Add(value)) throw new InvalidOperationException("Cyclic tool return value.");
                var items = new List<JsonValue>();
                foreach (var item in enumerable)
                {
                    JsonValue child;
                    if (item is null) child = JsonNull.Instance;
                    else if (!TryToJson(item, seen, out child))
                    {
                        seen.Remove(value); json = null!; return false;
                    }
                    items.Add(child);
                }
                seen.Remove(value); json = new JsonArray(items); return true;
            default: json = null!; return false;
        }
    }
    private static ToolLoopException Invalid(string message) => new(message, hint: "Use a supported JSON-shaped delegate signature or the explicit Tool constructor.");
}
