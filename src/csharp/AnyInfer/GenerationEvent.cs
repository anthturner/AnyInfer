namespace AnyInfer;

public abstract record GenerationEvent;

public sealed record AttemptStartedEvent(int EntryOrdinal, string Role) : GenerationEvent;

public sealed record FirstTokenEvent(int EntryOrdinal) : GenerationEvent;

public sealed record TextDeltaEvent(string Text) : GenerationEvent;

public sealed record UsageEvent(Usage Usage) : GenerationEvent;

public sealed record AttemptFailedEvent(AttemptRecord Attempt) : GenerationEvent;

public sealed record StreamEndedEvent(GenerationResult Result) : GenerationEvent;
