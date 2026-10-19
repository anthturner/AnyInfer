namespace AnyInfer;

public abstract record StreamEvent;

public sealed record TimingMark(string Name, double AtMs) : StreamEvent;

public sealed record TextDelta(string Text) : StreamEvent;

/// <summary>One fragment of a model-requested tool call, correlated by native index.</summary>
public sealed record ToolCallDelta(int Index, string? CallId, string? Name, string ArgumentsFragment) : StreamEvent;

public sealed record UsageUpdate(Usage Usage) : StreamEvent;

public sealed record AttemptFailed(AttemptRecord Record) : StreamEvent;

public sealed record StreamEnded(Generation Result) : StreamEvent;
