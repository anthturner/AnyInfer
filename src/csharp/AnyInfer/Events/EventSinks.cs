using System.Diagnostics;
using AnyInfer.Json;

namespace AnyInfer.Events;

/// <summary>Writes redacted telemetry events to a caller-selected trace source.</summary>
/// <remarks>
/// Each event is written as one compact JSON line (the <see cref="TelemetryEvent.ToDictionary"/> projection, with
/// sorted keys and ASCII escaping) through <see cref="TraceSource.TraceEvent(TraceEventType, int, string)"/> with
/// event id <c>0</c>. Whether anything is recorded depends on the trace source's switch and listeners.
/// </remarks>
public sealed class LoggingObserver : IObserver
{
    private readonly TraceSource _source;
    private readonly TraceEventType _level;

    /// <summary>Initializes a logging observer.</summary>
    /// <param name="source">
    /// The trace source to write to. When <see langword="null"/>, the observer creates a new trace source named
    /// <c>AnyInfer.Telemetry</c>, whose switch is off unless it is configured externally.
    /// </param>
    /// <param name="level">The trace event type every event is written at.</param>
    /// <exception cref="ArgumentOutOfRangeException">The level is not a defined trace event type.</exception>
    public LoggingObserver(TraceSource? source = null, TraceEventType level = TraceEventType.Information)
    {
        if (!Enum.IsDefined(level))
        {
            throw new ArgumentOutOfRangeException(nameof(level));
        }

        _source = source ?? new TraceSource("AnyInfer.Telemetry");
        _level = level;
    }

    /// <summary>Writes one redacted telemetry event.</summary>
    /// <param name="telemetryEvent">The event to write.</param>
    /// <exception cref="ArgumentNullException"><paramref name="telemetryEvent"/> is <see langword="null"/>.</exception>
    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        var value = telemetryEvent.ToDictionary();
        _source.TraceEvent(_level, 0, JsonWriter.WriteManifestCanonical(value));
    }
}

/// <summary>Appends redacted telemetry events to a caller-owned JSONL file.</summary>
/// <remarks>
/// Each event is appended as one compact JSON line (the <see cref="TelemetryEvent.ToDictionary"/> projection, with
/// sorted keys and ASCII escaping). Writes are serialized, so one instance can be shared by concurrent requests.
/// The file stays open until <see cref="Dispose"/> or <see cref="Close"/>; events received after that are
/// silently discarded.
/// </remarks>
public sealed class JsonlObserver : IObserver, IDisposable
{
    private readonly object _gate = new();
    private readonly StreamWriter _writer;
    private readonly bool _flush;
    private bool _closed;

    /// <summary>Opens a JSONL append sink.</summary>
    /// <param name="path">
    /// The file to append to. Missing parent directories are created. Other processes may read the file while it is
    /// open. On platforms other than Windows the file's permissions are set to owner read and write only.
    /// </param>
    /// <param name="flush">
    /// <see langword="true"/> to flush after every event; <see langword="false"/> to rely on buffering until the
    /// sink is closed.
    /// </param>
    /// <exception cref="ArgumentNullException"><paramref name="path"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentException"><paramref name="path"/> is empty.</exception>
    /// <exception cref="IOException">The directory or file cannot be created or opened.</exception>
    /// <exception cref="UnauthorizedAccessException">The caller lacks permission to create or open the file.</exception>
    public JsonlObserver(string path, bool flush = true)
    {
        ArgumentException.ThrowIfNullOrEmpty(path);
        var directory = Path.GetDirectoryName(Path.GetFullPath(path));
        Directory.CreateDirectory(directory!);
        _writer = new StreamWriter(new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read));
        _flush = flush;
        if (!OperatingSystem.IsWindows())
        {
            try { File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite); } catch (PlatformNotSupportedException) { }
        }
    }

    /// <summary>Appends one redacted event and optionally flushes it.</summary>
    /// <param name="telemetryEvent">The event to append. It is ignored when the sink is already closed.</param>
    /// <exception cref="ArgumentNullException"><paramref name="telemetryEvent"/> is <see langword="null"/>.</exception>
    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        var line = JsonWriter.WriteManifestCanonical(telemetryEvent.ToDictionary());
        lock (_gate)
        {
            if (_closed) return;
            _writer.WriteLine(line);
            if (_flush) _writer.Flush();
        }
    }

    /// <summary>Closes the caller-owned file sink.</summary>
    /// <remarks>Equivalent to <see cref="Dispose"/>; calling it more than once has no further effect.</remarks>
    public void Close() => Dispose();

    /// <summary>Closes the caller-owned file sink.</summary>
    /// <remarks>Flushes buffered lines and releases the file; calling it more than once has no further effect.</remarks>
    public void Dispose()
    {
        lock (_gate)
        {
            if (_closed) return;
            _closed = true;
            _writer.Dispose();
        }
    }
}
