namespace AnyInfer;

public abstract record StreamEvent;

public sealed record TimingMark(string Name, double AtMs) : StreamEvent;

public sealed record TextDelta(string Text) : StreamEvent;

public sealed record UsageUpdate(Usage Usage) : StreamEvent;

public sealed record AttemptFailed(AttemptRecord Record) : StreamEvent;

public sealed record StreamEnded(Generation Result) : StreamEvent;
