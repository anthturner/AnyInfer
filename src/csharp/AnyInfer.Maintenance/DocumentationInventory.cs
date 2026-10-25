using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

internal sealed record DocumentationInventoryArguments(string Output, string? Assembly)
{
    internal static bool IsRequested(string[] args) => args.Length > 0 && args[0] == "--documentation-api";

    internal static DocumentationInventoryArguments Parse(string[] args)
    {
        const string usage = "Usage: AnyInfer.Maintenance --documentation-api --output OUTPUT_JSON [--assembly ASSEMBLY_PATH]";
        if (args.Length is not (3 or 5) || args[0] != "--documentation-api" || args[1] != "--output" || string.IsNullOrWhiteSpace(args[2]))
            throw new ArgumentException(usage);
        if (args.Length == 3) return new DocumentationInventoryArguments(args[2], null);
        if (args[3] != "--assembly" || string.IsNullOrWhiteSpace(args[4])) throw new ArgumentException(usage);
        return new DocumentationInventoryArguments(args[2], args[4]);
    }
}

/// <summary>
/// One documentable public or protected declaration, keyed by its canonical XML documentation ID.
/// </summary>
/// <param name="Id">The canonical XML documentation ID.</param>
/// <param name="Kind">The declaration kind, such as <c>method</c> or <c>record</c>.</param>
/// <param name="Signature">A short readable C# signature.</param>
/// <param name="Parameters">Parameter names that require <c>param</c> documentation.</param>
/// <param name="TypeParameters">Type parameter names the declaration itself introduces.</param>
/// <param name="Returns">Whether the declaration returns a value that requires <c>returns</c> documentation.</param>
/// <param name="Inherits">Whether the declaration overrides or implements a member it may inherit documentation from.</param>
internal sealed record DocumentedSymbol(
    string Id,
    string Kind,
    string Signature,
    IReadOnlyList<string> Parameters,
    IReadOnlyList<string> TypeParameters,
    bool Returns,
    bool Inherits);

/// <summary>
/// Enumerates every documentable declaration an assembly exports, as compiler-compatible XML
/// documentation IDs. Unlike <see cref="PublicApi"/>, overloads, constructors, operators,
/// indexers, enum values and events are each distinct entries.
/// </summary>
/// <remarks>
/// The only declarations left out are ones a caller cannot reach or the C# language defines:
/// accessors (documented by their property or event), the <c>value__</c> field of an enum, the
/// runtime-supplied members of a delegate, static constructors, members hidden by a sealed or
/// non-public declaring type, and the members the compiler synthesizes for a record (value
/// equality, <c>ToString</c>, <c>PrintMembers</c>, <c>Deconstruct</c>, the copy constructor,
/// <c>EqualityContract</c> and <c>&lt;Clone&gt;$</c>). A record member the author declares
/// explicitly carries no <see cref="CompilerGeneratedAttribute"/> and stays in the inventory.
/// Implicitly declared constructors are deliberately kept: they are callable API, so a type
/// that exposes one must declare and document it.
/// </remarks>
internal static class DocumentationInventory
{
    private const BindingFlags Declared =
        BindingFlags.DeclaredOnly | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;

    private static readonly HashSet<string> SynthesizedRecordMembers = new(StringComparer.Ordinal)
    {
        "Equals", "GetHashCode", "ToString", "PrintMembers", "Deconstruct", "op_Equality", "op_Inequality",
        "<Clone>$", "EqualityContract", ".ctor",
    };

    internal static async Task WriteAsync(string output, string? assemblyPath)
    {
        var assembly = assemblyPath is null
            ? typeof(AnyInfer.AsyncClient).Assembly
            : Assembly.LoadFrom(Path.GetFullPath(assemblyPath));
        var symbols = Symbols(assembly);
        using var rendered = new MemoryStream();
        using (var writer = new Utf8JsonWriter(rendered, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteNumber("schema_version", 1);
            writer.WriteString("assembly", assembly.GetName().Name);
            writer.WritePropertyName("symbols");
            writer.WriteStartArray();
            foreach (var symbol in symbols)
            {
                writer.WriteStartObject();
                writer.WriteString("id", symbol.Id);
                writer.WriteString("kind", symbol.Kind);
                writer.WriteString("signature", symbol.Signature);
                writer.WritePropertyName("parameters");
                writer.WriteStartArray();
                foreach (var parameter in symbol.Parameters) writer.WriteStringValue(parameter);
                writer.WriteEndArray();
                writer.WritePropertyName("type_parameters");
                writer.WriteStartArray();
                foreach (var parameter in symbol.TypeParameters) writer.WriteStringValue(parameter);
                writer.WriteEndArray();
                writer.WriteBoolean("returns", symbol.Returns);
                writer.WriteBoolean("inherits", symbol.Inherits);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();
            writer.WriteEndObject();
        }
        var text = Encoding.UTF8.GetString(rendered.ToArray()).Replace("\r\n", "\n", StringComparison.Ordinal) + "\n";
        await File.WriteAllTextAsync(output, text, new UTF8Encoding(false));
    }

    internal static IReadOnlyList<DocumentedSymbol> Symbols(Assembly assembly)
    {
        var symbols = new Dictionary<string, DocumentedSymbol>(StringComparer.Ordinal);
        void Add(DocumentedSymbol symbol)
        {
            if (!symbols.TryAdd(symbol.Id, symbol))
                throw new InvalidOperationException($"Duplicate documentation ID {symbol.Id}.");
        }

        foreach (var type in assembly.GetExportedTypes())
        {
            var invoke = typeof(Delegate).IsAssignableFrom(type) ? type.GetMethod("Invoke") : null;
            Add(new DocumentedSymbol(
                "T:" + TypeId(type),
                TypeKind(type),
                DisplayType(type),
                invoke is null ? PrimaryParameters(type) : Names(invoke.GetParameters()),
                OwnTypeParameters(type),
                invoke is not null && ReturnsValue(invoke.ReturnType),
                false));
            var record = IsRecord(type);
            var inheritable = !type.IsSealed;
            if (typeof(Delegate).IsAssignableFrom(type)) continue;

            foreach (var constructor in type.GetConstructors(Declared))
            {
                if (constructor.IsStatic || !Visible(constructor, inheritable)) continue;
                if (record && IsSynthesizedRecordMember(constructor)) continue;
                Add(new DocumentedSymbol(
                    MethodId(constructor), "constructor", DisplayMethod(constructor), Names(constructor.GetParameters()), [], false, false));
            }
            foreach (var method in type.GetMethods(Declared))
            {
                if (!Visible(method, inheritable)) continue;
                if (record && IsSynthesizedRecordMember(method)) continue;
                var isOperator = method.IsSpecialName && method.Name.StartsWith("op_", StringComparison.Ordinal);
                if (method.IsSpecialName && !isOperator) continue;
                Add(new DocumentedSymbol(
                    MethodId(method),
                    isOperator ? "operator" : "method",
                    DisplayMethod(method),
                    Names(method.GetParameters()),
                    method.IsGenericMethodDefinition ? method.GetGenericArguments().Select(static argument => argument.Name).ToArray() : [],
                    ReturnsValue(method.ReturnType),
                    Inherits(method)));
            }
            foreach (var property in type.GetProperties(Declared))
            {
                var accessors = property.GetAccessors(nonPublic: true);
                if (!accessors.Any(accessor => Visible(accessor, inheritable))) continue;
                if (record && IsSynthesizedRecordMember(property)) continue;
                var indexed = property.GetIndexParameters();
                Add(new DocumentedSymbol(
                    "P:" + TypeId(type) + "." + property.Name + Parameters(indexed),
                    indexed.Length == 0 ? "property" : "indexer",
                    property.Name + (indexed.Length == 0 ? string.Empty : "[" + string.Join(", ", indexed.Select(DisplayParameter)) + "]"),
                    Names(indexed),
                    [],
                    false,
                    accessors.Any(Inherits)));
            }
            foreach (var field in type.GetFields(Declared))
            {
                if (field.IsSpecialName || !Visible(field, inheritable)) continue;
                if (field.IsDefined(typeof(CompilerGeneratedAttribute), inherit: false)) continue;
                Add(new DocumentedSymbol(
                    "F:" + TypeId(type) + "." + field.Name, type.IsEnum ? "enum-value" : "field", field.Name, [], [], false, false));
            }
            foreach (var @event in type.GetEvents(Declared))
            {
                var accessor = @event.AddMethod ?? @event.RemoveMethod;
                if (accessor is null || !Visible(accessor, inheritable)) continue;
                Add(new DocumentedSymbol("E:" + TypeId(type) + "." + @event.Name, "event", @event.Name, [], [], false, Inherits(accessor)));
            }
        }
        return symbols.Values.OrderBy(static symbol => symbol.Id, StringComparer.Ordinal).ToArray();
    }

    /// <summary>
    /// A bare <see cref="Task"/> or <see cref="ValueTask"/> carries completion, not a value, so its
    /// meaning belongs in the summary rather than in a separate <c>returns</c> element.
    /// </summary>
    private static bool ReturnsValue(Type type) =>
        type != typeof(void) && type != typeof(Task) && type != typeof(ValueTask);

    private static string[] Names(ParameterInfo[] parameters) =>
        parameters.Select(static parameter => parameter.Name ?? throw new InvalidOperationException("A public parameter has no name.")).ToArray();

    /// <summary>Returns a positional record's parameters, which its own comment documents.</summary>
    private static string[] PrimaryParameters(Type type)
    {
        if (!IsRecord(type)) return [];
        var positional = type.GetProperties(Declared)
            .Where(property => property.GetMethod?.IsDefined(typeof(CompilerGeneratedAttribute), inherit: false) == true)
            .Select(static property => property.Name)
            .ToHashSet(StringComparer.Ordinal);
        var primary = type.GetConstructors(Declared)
            .Where(constructor => !constructor.IsStatic && !IsSynthesizedRecordMember(constructor))
            .Select(static constructor => constructor.GetParameters())
            .FirstOrDefault(parameters => parameters.Length > 0 && parameters.All(parameter => positional.Contains(parameter.Name!)));
        return primary is null ? [] : Names(primary);
    }

    private static string[] OwnTypeParameters(Type type)
    {
        var all = type.GetGenericArguments();
        var inherited = type.DeclaringType?.GetGenericArguments().Length ?? 0;
        return all.Skip(inherited).Select(static argument => argument.Name).ToArray();
    }

    private static bool Inherits(MethodInfo method)
    {
        if (method.GetBaseDefinition().DeclaringType != method.DeclaringType) return true;
        var type = method.DeclaringType!;
        if (type.IsInterface) return false;
        return type.GetInterfaces().Any(contract => type.GetInterfaceMap(contract).TargetMethods.Contains(method));
    }

    private static bool Visible(MethodBase method, bool inheritable) =>
        method.IsPublic || (inheritable && (method.IsFamily || method.IsFamilyOrAssembly));

    private static bool Visible(FieldInfo field, bool inheritable) =>
        field.IsPublic || (inheritable && (field.IsFamily || field.IsFamilyOrAssembly));

    private static bool IsRecord(Type type) =>
        type.GetMethod("PrintMembers", Declared, [typeof(StringBuilder)]) is { } printMembers
        && printMembers.IsDefined(typeof(CompilerGeneratedAttribute), inherit: false);

    private static bool IsSynthesizedRecordMember(MemberInfo member)
    {
        if (!SynthesizedRecordMembers.Contains(member.Name)) return false;
        if (member is ConstructorInfo constructor)
        {
            // Only the copy constructor is synthesized; a positional record's primary
            // constructor is authored through the record's own parameter list.
            var parameters = constructor.GetParameters();
            return parameters.Length == 1 && parameters[0].ParameterType == constructor.DeclaringType
                && constructor.IsDefined(typeof(CompilerGeneratedAttribute), inherit: false);
        }
        if (member is PropertyInfo property)
            return property.GetMethod?.IsDefined(typeof(CompilerGeneratedAttribute), inherit: false) == true;
        return member.IsDefined(typeof(CompilerGeneratedAttribute), inherit: false);
    }

    private static string TypeKind(Type type)
    {
        if (type.IsEnum) return "enum";
        if (type.IsInterface) return "interface";
        if (typeof(Delegate).IsAssignableFrom(type)) return "delegate";
        if (type.IsValueType) return IsRecord(type) ? "record-struct" : "struct";
        return IsRecord(type) ? "record" : "class";
    }

    /// <summary>Returns a type definition's documentation name, for example <c>N.Outer`1.Inner</c>.</summary>
    private static string TypeId(Type type)
    {
        if (type.IsNested) return TypeId(type.DeclaringType!) + "." + type.Name;
        return string.IsNullOrEmpty(type.Namespace) ? type.Name : type.Namespace + "." + type.Name;
    }

    private static string MethodId(MethodBase method)
    {
        var name = method is ConstructorInfo ? "#ctor" : method.Name;
        var arity = method.IsGenericMethodDefinition ? "``" + method.GetGenericArguments().Length : string.Empty;
        var id = "M:" + TypeId(method.DeclaringType!) + "." + name + arity + Parameters(method.GetParameters());
        if (method is MethodInfo info && info.Name is "op_Implicit" or "op_Explicit")
            id += "~" + ParameterType(info.ReturnType);
        return id;
    }

    private static string Parameters(ParameterInfo[] parameters) =>
        parameters.Length == 0 ? string.Empty : "(" + string.Join(",", parameters.Select(parameter => ParameterType(parameter.ParameterType))) + ")";

    /// <summary>Encodes a parameter type using the documentation-ID grammar.</summary>
    private static string ParameterType(Type type)
    {
        if (type.IsByRef) return ParameterType(type.GetElementType()!) + "@";
        if (type.IsPointer) return ParameterType(type.GetElementType()!) + "*";
        if (type.IsArray)
        {
            var rank = type.GetArrayRank();
            var shape = rank == 1 && type.IsSZArray ? "[]" : "[" + string.Join(",", Enumerable.Repeat("0:", rank)) + "]";
            return ParameterType(type.GetElementType()!) + shape;
        }
        if (type.IsGenericParameter)
            return (type.DeclaringMethod is null ? "`" : "``") + type.GenericParameterPosition;
        if (!type.IsGenericType) return TypeId(type);

        // A constructed type spreads its arguments across each nesting level by that
        // level's own arity, as in N.Outer{`0}.Inner{System.Int32}.
        var arguments = type.GetGenericArguments();
        var levels = new List<Type>();
        for (var current = type.GetGenericTypeDefinition(); current is not null; current = current.DeclaringType)
            levels.Insert(0, current);
        var builder = new StringBuilder();
        var consumed = 0;
        foreach (var level in levels)
        {
            if (builder.Length == 0)
                builder.Append(string.IsNullOrEmpty(level.Namespace) ? string.Empty : level.Namespace + ".");
            else
                builder.Append('.');
            var tick = level.Name.IndexOf('`', StringComparison.Ordinal);
            builder.Append(tick < 0 ? level.Name : level.Name[..tick]);
            var total = level.GetGenericArguments().Length;
            var own = total - consumed;
            if (own > 0)
            {
                builder.Append('{')
                    .Append(string.Join(",", arguments.Skip(consumed).Take(own).Select(ParameterType)))
                    .Append('}');
            }
            consumed = total;
        }
        return builder.ToString();
    }

    private static string DisplayMethod(MethodBase method)
    {
        var name = method is ConstructorInfo ? DisplayName(method.DeclaringType!) : method.Name;
        var generics = method.IsGenericMethodDefinition
            ? "<" + string.Join(", ", method.GetGenericArguments().Select(static argument => argument.Name)) + ">"
            : string.Empty;
        return name + generics + "(" + string.Join(", ", method.GetParameters().Select(DisplayParameter)) + ")";
    }

    private static string DisplayParameter(ParameterInfo parameter)
    {
        var type = parameter.ParameterType;
        var prefix = string.Empty;
        if (type.IsByRef)
        {
            prefix = parameter.IsOut ? "out " : parameter.IsIn ? "in " : "ref ";
            type = type.GetElementType()!;
        }
        else if (parameter.IsDefined(typeof(ParamArrayAttribute), inherit: false))
        {
            prefix = "params ";
        }
        return prefix + DisplayType(type);
    }

    private static string DisplayType(Type type)
    {
        if (type.IsArray) return DisplayType(type.GetElementType()!) + "[" + new string(',', type.GetArrayRank() - 1) + "]";
        if (Nullable.GetUnderlyingType(type) is { } underlying) return DisplayType(underlying) + "?";
        var alias = Type.GetTypeCode(type) switch
        {
            TypeCode.Boolean => "bool",
            TypeCode.Byte => "byte",
            TypeCode.Char => "char",
            TypeCode.Decimal => "decimal",
            TypeCode.Double => "double",
            TypeCode.Int16 => "short",
            TypeCode.Int32 => "int",
            TypeCode.Int64 => "long",
            TypeCode.SByte => "sbyte",
            TypeCode.Single => "float",
            TypeCode.String => "string",
            TypeCode.UInt16 => "ushort",
            TypeCode.UInt32 => "uint",
            TypeCode.UInt64 => "ulong",
            _ => null,
        };
        if (alias is not null && !type.IsEnum) return alias;
        if (type == typeof(object)) return "object";
        if (type == typeof(void)) return "void";
        return DisplayName(type);
    }

    private static string DisplayName(Type type)
    {
        var tick = type.Name.IndexOf('`', StringComparison.Ordinal);
        var name = tick < 0 ? type.Name : type.Name[..tick];
        if (!type.IsGenericType) return name;
        var own = type.GetGenericArguments();
        if (type.DeclaringType is { } outer)
            own = own.Skip(outer.GetGenericArguments().Length).ToArray();
        return own.Length == 0 ? name : name + "<" + string.Join(", ", own.Select(DisplayType)) + ">";
    }
}
