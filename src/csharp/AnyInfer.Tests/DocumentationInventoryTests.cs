using AnyInfer.Tests.DocumentationInventoryShapes;
using Xunit;

namespace AnyInfer.Tests
{
    /// <summary>Controls for the documentable-declaration inventory's IDs and exclusion policy.</summary>
    public sealed class DocumentationInventoryTests
    {
        private const string Prefix = "AnyInfer.Tests.DocumentationInventoryShapes.";

        private static readonly IReadOnlyDictionary<string, DocumentedSymbol> Shapes =
            DocumentationInventory.Symbols(typeof(DocumentationInventoryTests).Assembly)
                .Where(static symbol => symbol.Id[2..].StartsWith(Prefix, StringComparison.Ordinal))
                .ToDictionary(static symbol => symbol.Id[..2] + symbol.Id[(2 + Prefix.Length)..]);

        [Fact]
        public void Every_overload_constructor_operator_indexer_and_event_is_a_distinct_entry()
        {
            Assert.Contains("M:Overloaded.Run", Shapes.Keys);
            Assert.Contains("M:Overloaded.Run(System.Int32)", Shapes.Keys);
            Assert.Contains("M:Overloaded.Run(System.String,System.Int32[],System.Int32[0:,0:])", Shapes.Keys);
            Assert.Contains("M:Overloaded.#ctor", Shapes.Keys);
            Assert.Contains("M:Overloaded.#ctor(System.Int32)", Shapes.Keys);
            Assert.Contains("M:Overloaded.op_Addition(AnyInfer.Tests.DocumentationInventoryShapes.Overloaded,AnyInfer.Tests.DocumentationInventoryShapes.Overloaded)", Shapes.Keys);
            Assert.Contains("M:Overloaded.op_Implicit(System.Int32)~AnyInfer.Tests.DocumentationInventoryShapes.Overloaded", Shapes.Keys);
            Assert.Contains("P:Overloaded.Item(System.String)", Shapes.Keys);
            Assert.Contains("E:Overloaded.Changed", Shapes.Keys);
            Assert.Equal("indexer", Shapes["P:Overloaded.Item(System.String)"].Kind);
            Assert.Equal("operator", Shapes["M:Overloaded.op_Addition(AnyInfer.Tests.DocumentationInventoryShapes.Overloaded,AnyInfer.Tests.DocumentationInventoryShapes.Overloaded)"].Kind);
            Assert.DoesNotContain(Shapes.Keys, static id => id.Contains(".get_", StringComparison.Ordinal) || id.Contains(".add_", StringComparison.Ordinal));
        }

        [Fact]
        public void Generic_nested_and_by_reference_shapes_use_documentation_id_grammar()
        {
            Assert.Contains("T:Outer`1", Shapes.Keys);
            Assert.Contains("T:Outer`1.Inner`1", Shapes.Keys);
            Assert.Contains("M:Outer`1.Inner`1.Pair``1(`0,`1,``0)", Shapes.Keys);
            Assert.Contains("M:Outer`1.Inner`1.Swap(`0@,System.Nullable{System.Int32}@,System.String@)", Shapes.Keys);
            Assert.Contains("M:Consumer.Use(AnyInfer.Tests.DocumentationInventoryShapes.Outer{System.Int32}.Inner{System.String},System.Collections.Generic.IReadOnlyDictionary{System.String,System.Collections.Generic.IReadOnlyList{System.Int32}})", Shapes.Keys);
            Assert.Equal(["T"], Shapes["T:Outer`1"].TypeParameters);
            Assert.Equal(["TInner"], Shapes["T:Outer`1.Inner`1"].TypeParameters);
            Assert.Equal(["TResult"], Shapes["M:Outer`1.Inner`1.Pair``1(`0,`1,``0)"].TypeParameters);
            Assert.Equal("Swap(ref T, out int?, in string)", Shapes["M:Outer`1.Inner`1.Swap(`0@,System.Nullable{System.Int32}@,System.String@)"].Signature);
        }

        [Fact]
        public void Synthesized_record_members_are_excluded_but_declared_ones_are_kept()
        {
            var record = Shapes.Keys.Where(static id => id[2..].StartsWith("Point", StringComparison.Ordinal)).Order(StringComparer.Ordinal).ToArray();
            Assert.Equal(
                [
                    "M:Point.#ctor(System.Int32,System.Int32)",
                    "M:Point.ToString",
                    "P:Point.X",
                    "P:Point.Y",
                    "T:Point",
                ],
                record);
            Assert.Equal("record", Shapes["T:Point"].Kind);
            Assert.Equal(["X", "Y"], Shapes["T:Point"].Parameters);
            Assert.True(Shapes["M:Point.ToString"].Inherits);
            Assert.Equal("record-struct", Shapes["T:Measure"].Kind);
            Assert.Contains("P:Measure.Value", Shapes.Keys);
            Assert.DoesNotContain(Shapes.Keys, static id => id.StartsWith("M:Measure.Equals", StringComparison.Ordinal));
        }

        [Fact]
        public void Implicit_constructors_stay_and_unreachable_members_do_not()
        {
            Assert.Contains("M:Implicit.#ctor", Shapes.Keys);
            Assert.Contains("M:Unsealed.Hook", Shapes.Keys);
            Assert.Contains("F:Unsealed.Shared", Shapes.Keys);
            Assert.DoesNotContain("M:Sealed.Hook", Shapes.Keys);
            Assert.DoesNotContain(Shapes.Keys, static id => id.Contains("Hidden", StringComparison.Ordinal));
            Assert.DoesNotContain(Shapes.Keys, static id => id.Contains(".#cctor", StringComparison.Ordinal));
        }

        [Fact]
        public void Delegates_and_enums_keep_only_their_declared_surface()
        {
            Assert.Equal(["T:Callback"], Shapes.Keys.Where(static id => id.Contains("Callback", StringComparison.Ordinal)).ToArray());
            Assert.Equal(["input", "count"], Shapes["T:Callback"].Parameters);
            Assert.True(Shapes["T:Callback"].Returns);
            Assert.Equal(
                ["F:Level.High", "F:Level.Low", "T:Level"],
                Shapes.Keys.Where(static id => id[2..].StartsWith("Level", StringComparison.Ordinal)).Order(StringComparer.Ordinal).ToArray());
        }

        [Fact]
        public void Bare_tasks_need_no_returns_and_generic_tasks_do()
        {
            Assert.False(Shapes["M:Overloaded.RunAsync"].Returns);
            Assert.True(Shapes["M:Overloaded.CountAsync"].Returns);
            Assert.False(Shapes["M:Overloaded.Run"].Returns);
            Assert.True(Shapes["M:Overloaded.Run(System.Int32)"].Returns);
        }

        [Fact]
        public void Arguments_reject_unknown_shapes()
        {
            Assert.Equal(new DocumentationInventoryArguments("out.json", null), DocumentationInventoryArguments.Parse(["--documentation-api", "--output", "out.json"]));
            Assert.Equal(new DocumentationInventoryArguments("out.json", "a.dll"), DocumentationInventoryArguments.Parse(["--documentation-api", "--output", "out.json", "--assembly", "a.dll"]));
            Assert.Throws<ArgumentException>(() => DocumentationInventoryArguments.Parse(["--documentation-api", "--output"]));
            Assert.Throws<ArgumentException>(() => DocumentationInventoryArguments.Parse(["--documentation-api", "--output", "out.json", "--other", "a.dll"]));
        }
    }
}

namespace AnyInfer.Tests.DocumentationInventoryShapes
{
    public sealed class Overloaded
    {
        public Overloaded() { }
        public Overloaded(int seed) => Seed = seed;
        public int Seed { get; }
        public string this[string key] => key;
        public event EventHandler? Changed;
        public void Run() => Changed?.Invoke(this, EventArgs.Empty);
        public int Run(int count) => count;
        public int Run(string name, int[] values, int[,] grid) => name.Length + values.Length + grid.Length;
        public Task RunAsync() => Task.CompletedTask;
        public Task<int> CountAsync() => Task.FromResult(Seed);
        public static Overloaded operator +(Overloaded left, Overloaded right) => new(left.Seed + right.Seed);
        public static implicit operator Overloaded(int seed) => new(seed);
    }

    public class Outer<T>
    {
        public sealed class Inner<TInner>
        {
            public (T, TInner, TResult) Pair<TResult>(T first, TInner second, TResult third) => (first, second, third);
            public void Swap(ref T value, out int? count, in string label) => count = label.Length;
        }
    }

    public static class Consumer
    {
        public static int Use(Outer<int>.Inner<string> inner, IReadOnlyDictionary<string, IReadOnlyList<int>> map) => map.Count;
    }

    public sealed record Point(int X, int Y)
    {
        public override string ToString() => $"{X},{Y}";
    }

    public readonly record struct Measure(double Value);

    public sealed class Implicit { }

    public class Unsealed
    {
        protected static readonly int Shared = 1;
        protected virtual void Hook() { }
        private protected void Hidden() { }
        internal void HiddenToo() { }
        static Unsealed() { }
    }

    public sealed class Sealed : Unsealed
    {
        protected override void Hook() { }
    }

    public delegate bool Callback(string input, int count);

    public enum Level
    {
        Low,
        High,
    }
}
