using System.Diagnostics;
using AnyInfer.Json;

namespace AnyInfer.Events;

/// <summary>Writes redacted telemetry events to a caller-selected trace source.</summary>
public sealed class LoggingObserver : IObserver
{
    private readonly TraceSource _source;
    private readonly TraceEventType _level;

    /// <summary>Initializes a logging observer.</summary>
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
    public void OnEvent(TelemetryEvent telemetryEvent)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        var value = telemetryEvent.ToDictionary();
        _source.TraceEvent(_level, 0, JsonWriter.WriteManifestCanonical(value));
    }
}

/// <summary>Appends redacted telemetry events to a caller-owned JSONL file.</summary>
public sealed class JsonlObserver : IObserver, IDisposable
{
    private readonly object _gate = new();
    private readonly StreamWriter _writer;
    private readonly bool _flush;
    private bool _closed;

    /// <summary>Opens a JSONL append sink.</summary>
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
    public void Close() => Dispose();

    /// <summary>Closes the caller-owned file sink.</summary>
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
