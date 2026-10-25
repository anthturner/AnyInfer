namespace ReferenceFixture;

/// <summary>Holds <typeparamref name="T"/> values and links to <see cref="Pair{TLeft, TRight}"/>.</summary>
/// <typeparam name="T">The stored value type.</typeparam>
/// <remarks>Escaping check: <c>a &lt; b &amp;&amp; c &gt; d</c> and braces {literal}.</remarks>
public class Box<T> where T : notnull
{
    /// <summary>Creates an empty box.</summary>
    public Box() { }

    /// <summary>Creates a box holding <paramref name="value"/>.</summary>
    /// <param name="value">The initial value.</param>
    public Box(T value) => Value = value;

    /// <summary>Gets the stored value, or <see langword="null"/> when empty.</summary>
    public T? Value { get; }

    /// <summary>Projects the value.</summary>
    /// <typeparam name="TResult">The projected type.</typeparam>
    /// <param name="selector">The projection.</param>
    /// <returns>A new box.</returns>
    /// <exception cref="InvalidOperationException">The box is empty.</exception>
    public Box<TResult> Map<TResult>(Func<T, TResult> selector) where TResult : notnull =>
        Value is { } value ? new Box<TResult>(selector(value)) : throw new InvalidOperationException("empty");

    /// <summary>Overload taking a fallback.</summary>
    /// <typeparam name="TResult">The projected type.</typeparam>
    /// <param name="selector">The projection.</param>
    /// <param name="fallback">The value used when the box is empty.</param>
    /// <returns>A new box.</returns>
    public Box<TResult> Map<TResult>(Func<T, TResult> selector, TResult fallback) where TResult : notnull =>
        Value is { } value ? new Box<TResult>(selector(value)) : new Box<TResult>(fallback);

    /// <summary>A nested type whose implicit public constructor is deliberately undeclared.</summary>
    public sealed class Nested
    {
        /// <summary>A doubly nested enum.</summary>
        public enum Depth
        {
            /// <summary>The first level.</summary>
            One = 1,
            /// <summary>The second level.</summary>
            Two = 2,
        }
    }

    /// <summary>A protected member visible to subclasses.</summary>
    protected virtual void OnChanged() { }
}

/// <summary>A positional record with compiler-generated members.</summary>
/// <param name="Left">The left value.</param>
/// <param name="Right">The right value.</param>
/// <typeparam name="TLeft">The left type.</typeparam>
/// <typeparam name="TRight">The right type.</typeparam>
public sealed record Pair<TLeft, TRight>(TLeft Left, TRight Right);

/// <summary>A value with operators and conversions.</summary>
/// <remarks>
/// Its positional <c>Value</c> parameter is deliberately undocumented: the compiler reports no
/// warning for that gap, so it is a negative control for the documentation checker.
/// </remarks>
public readonly record struct Meters(double Value)
{
    /// <summary>Adds two lengths.</summary>
    /// <param name="left">The left operand.</param>
    /// <param name="right">The right operand.</param>
    /// <returns>The sum.</returns>
    public static Meters operator +(Meters left, Meters right) => new(left.Value + right.Value);

    /// <summary>Converts a raw number.</summary>
    /// <param name="value">The raw value.</param>
    /// <returns>A length of <paramref name="value"/> meters.</returns>
    public static implicit operator Meters(double value) => new(value);

    /// <summary>Reads the raw number.</summary>
    /// <param name="value">The length.</param>
    /// <returns>The number of meters.</returns>
    public static explicit operator double(Meters value) => value.Value;
}

/// <summary>Reference, out, in, params, nullable and async-stream parameters.</summary>
public static class Signatures
{
    /// <summary>Tries to parse a value.</summary>
    /// <param name="text">The input text.</param>
    /// <param name="value">The parsed value.</param>
    /// <returns><see langword="true"/> when parsing succeeded.</returns>
    public static bool TryParse(string? text, out int value) => int.TryParse(text, out value);

    /// <summary>Swaps two values.</summary>
    /// <param name="left">The first value.</param>
    /// <param name="right">The second value.</param>
    public static void Swap(ref int left, ref int right) => (left, right) = (right, left);

    /// <summary>Reads a value without copying.</summary>
    /// <param name="value">The value.</param>
    /// <returns>The value.</returns>
    public static int Read(in int value) => value;

    /// <summary>Sums values.</summary>
    /// <param name="values">The values.</param>
    /// <returns>The sum.</returns>
    public static int Sum(params int[] values) => values.Sum();

    /// <summary>Streams numbers.</summary>
    /// <param name="count">How many numbers to produce.</param>
    /// <param name="cancellationToken">Stops enumeration.</param>
    /// <returns>An asynchronous sequence.</returns>
    public static async IAsyncEnumerable<int> CountAsync(
        int count,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        for (var index = 0; index < count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await Task.Yield();
            yield return index;
        }
    }

    /// <summary>A deliberately long signature.</summary>
    /// <param name="first">First.</param>
    /// <param name="second">Second.</param>
    /// <param name="third">Third.</param>
    /// <param name="fourth">Fourth.</param>
    /// <param name="fifth">Fifth.</param>
    /// <param name="sixth">Sixth.</param>
    /// <returns>A dictionary.</returns>
    public static IReadOnlyDictionary<string, IReadOnlyList<KeyValuePair<string, Box<string>?>>> Long(
        IReadOnlyDictionary<string, IReadOnlyList<KeyValuePair<string, Box<string>?>>>? first = null,
        string? second = "default",
        int third = 3,
        double? fourth = null,
        CancellationToken fifth = default,
        Box<Pair<int, string>>? sixth = null) => first ?? new Dictionary<string, IReadOnlyList<KeyValuePair<string, Box<string>?>>>();

    /// <summary>Extends a string.</summary>
    /// <param name="value">The receiver.</param>
    /// <returns>The value repeated.</returns>
    public static string Twice(this string value) => value + value;

    /// <summary>An obsolete member.</summary>
    /// <param name="left">The first addend.</param>
    /// <param name="right">The second addend.</param>
    /// <returns>The sum.</returns>
    [Obsolete("Use Sum instead.")]
    public static int Add(int left, int right) => left + right;
}

/// <summary>An interface with an event and an indexer.</summary>
public interface IShape
{
    /// <summary>Raised when the shape changes.</summary>
    event EventHandler? Changed;

    /// <summary>Gets a coordinate.</summary>
    /// <param name="index">The coordinate index.</param>
    int this[int index] { get; }
}

/// <summary>A delegate type.</summary>
/// <param name="shape">The shape.</param>
/// <returns>An area.</returns>
public delegate double Measure(IShape shape);

/// <summary>Overloads that share documentation through <c>inheritdoc</c>.</summary>
public sealed record Overloads
{
    /// <summary>Creates the formatter; declared so the public constructor is documented.</summary>
    public Overloads() { }

    /// <summary>Formats a value.</summary>
    /// <param name="value">The value to format.</param>
    /// <param name="width">The minimum width.</param>
    /// <returns>The formatted text.</returns>
    public string Format(int value, int width) => value.ToString().PadLeft(width);

    /// <summary>Formats a value with the default width.</summary>
    /// <inheritdoc cref="Format(int, int)"/>
    public string Format(int value) => Format(value, 0);

    /// <summary>An explicitly declared record member stays in the inventory.</summary>
    /// <returns>A fixed description.</returns>
    public override string ToString() => "overloads";
}

/// <summary>A constant holder.</summary>
public static class Constants
{
    /// <summary>A public constant.</summary>
    public const int Answer = 42;

    /// <summary>A static read-only field.</summary>
    public static readonly string Name = "fixture";
}
