namespace AnyInfer.Providers;

/// <summary>Raw event emitted by a provider adapter.</summary>
public abstract record AdapterEvent;

/// <summary>Raw text delta emitted by a provider adapter.</summary>
public sealed record AdapterTextDelta(string Text) : AdapterEvent;

/// <summary>Raw usage observation emitted by a provider adapter.</summary>
public sealed record AdapterUsage(Usage Usage) : AdapterEvent;

/// <summary>Raw terminal event emitted by a provider adapter.</summary>
public sealed record AdapterFinal(string FinishReason, Usage? Usage = null, AnyInfer.Json.JsonValue? Raw = null) : AdapterEvent;

/// <summary>One raw provider tool-call delta; argument fragments are not assembled at this layer.</summary>
/// <param name="Index">Native signed 32-bit correlation index; out-of-range wire integers are refused, while absent or noninteger indexes use positional fallback.</param>
/// <param name="CallId">Optional provider call identifier.</param>
/// <param name="Name">Optional provider tool name.</param>
/// <param name="ArgumentsFragment">Raw provider argument fragment.</param>
public sealed record AdapterToolCallDelta(int Index, string? CallId, string? Name, string ArgumentsFragment) : AdapterEvent;
