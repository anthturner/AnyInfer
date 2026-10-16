namespace AnyInfer.Providers;

public abstract record AdapterEvent;

public sealed record AdapterTextDelta(string Text) : AdapterEvent;

public sealed record AdapterUsage(Usage Usage) : AdapterEvent;

public sealed record AdapterFinal(string FinishReason, Usage? Usage = null) : AdapterEvent;
