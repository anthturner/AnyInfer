using System.Globalization;
using System.Text;
using AnyInfer.Json;

namespace AnyInfer.Manifest;

public static partial class ManifestUtilities
{
    /// <summary>Renders a manifest as a human-readable tree without a trailing newline.</summary>
    /// <param name="manifest">The immutable manifest to render.</param>
    /// <param name="width">The column budget used to wrap long reasons and notes.</param>
    /// <returns>A human-readable presentation of the manifest.</returns>
    /// <exception cref="ArgumentNullException"><paramref name="manifest"/> is <see langword="null"/>.</exception>
    /// <exception cref="ArgumentOutOfRangeException"><paramref name="width"/> is not positive and a line needs wrapping.</exception>
    public static string Render(RunManifest manifest, int width = 80)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        var lines = new List<string>();
        var status = manifest.Complete ? "complete" : "incomplete (stream not drained)";
        lines.Add($"run {(manifest.RequestId.Length == 0 ? "(unknown)" : manifest.RequestId)} - {status}");
        lines.Add($"  anyinfer {(manifest.AnyinferVersion.Length == 0 ? "?" : manifest.AnyinferVersion)}, manifest format {manifest.Format}");

        var route = manifest.Route;
        var requested = string.Join(", ", route.Requested);
        lines.Add("  route");
        lines.Add($"    requested   {(requested.Length == 0 ? "(none)" : requested)}");
        lines.Add($"    resolved    {(string.IsNullOrEmpty(route.Resolved) ? "(none)" : route.Resolved)}");
        foreach (var step in route.Considered)
        {
            var detail = step.Reason.Length == 0 ? string.Empty : " - " + step.Reason;
            AddWrapped(lines, $"    * {step.Target}: {step.Outcome}{detail}", width);
        }

        if (manifest.Attempts.Count != 0)
        {
            lines.Add("  attempts");
            foreach (var attempt in manifest.Attempts)
            {
                var parts = new List<string> { $"#{attempt.AttemptNumber}", attempt.Target, attempt.Outcome };
                if (attempt.TotalMs is { } totalMs) parts.Add(FormatRounded(totalMs) + "ms");
                if (attempt.FirstTokenMs is { } firstTokenMs) parts.Add("ttft " + FormatRounded(firstTokenMs) + "ms");
                if (attempt.QueuedMs is { } queuedMs && queuedMs != 0) parts.Add("queued " + FormatRounded(queuedMs) + "ms");
                lines.Add("    " + string.Join(" ", parts));
                if (attempt.Error is { } error)
                {
                    AddWrapped(lines, "      error: " + (error.Detail ?? "None"), width);
                }

                if (attempt.RetryDelayS is { } retryDelayS)
                {
                    lines.Add("      retry after " + retryDelayS.ToString("F2", CultureInfo.InvariantCulture) + "s");
                }
            }
        }

        var structured = manifest.Structured;
        if (structured.Requested)
        {
            lines.Add("  structured output");
            lines.Add($"    chosen      {structured.Chosen ?? "None"} (used: {(string.IsNullOrEmpty(structured.Used) ? "-" : structured.Used)})");
            foreach (var rung in structured.Ladder)
            {
                var suffix = rung.Reason.Length == 0 ? string.Empty : " - " + rung.Reason;
                AddWrapped(lines, $"    {(rung.Available ? "+" : "-")} {rung.Mechanism}{suffix}", width);
            }

            lines.Add($"    repairs     {structured.RepairAttempts}");
            foreach (var repair in structured.Repairs)
            {
                foreach (var error in repair.Errors)
                {
                    AddWrapped(lines, $"      #{repair.AttemptNumber}: {error}", width);
                }
            }
        }

        if (manifest.Capability.Facts.Count != 0)
        {
            lines.Add($"  capabilities ({manifest.Capability.Target})");
            foreach (var fact in manifest.Capability.Facts)
            {
                AddWrapped(lines, "    " + PadRightScalars(fact.Name, 20) + global::AnyInfer.Catalog.Catalog.PythonString(fact.Value) + " [" + fact.Provenance + "]", width);
            }
        }

        var cache = manifest.Cache;
        if (!string.IsNullOrEmpty(cache.PolicyMode) || !string.IsNullOrEmpty(cache.Mechanism) || (cache.ReadTokens is { } cacheReadTokens && cacheReadTokens != 0))
        {
            lines.Add("  cache");
            lines.Add($"    policy      {(string.IsNullOrEmpty(cache.PolicyMode) ? "(none)" : cache.PolicyMode)}");
            lines.Add($"    mechanism   {(string.IsNullOrEmpty(cache.Mechanism) ? "(none)" : cache.Mechanism)}");
            if (cache.MarkCount != 0) lines.Add($"    marks       {cache.MarkCount}");
            if (cache.ReadTokens is { } readTokens) lines.Add($"    reported    {readTokens} read");
        }

        foreach (var reduction in manifest.Context.Reductions)
        {
            lines.Add($"  reduced {reduction.Strategy} -> {reduction.Representation}: {reduction.SelectedCount}/{reduction.CandidateCount} kept, {reduction.OmittedCount} omitted");
        }

        foreach (var drop in manifest.Dropped)
        {
            AddWrapped(lines, $"  dropped {drop.Parameter}: {drop.Reason}", width);
        }

        var usage = manifest.Usage;
        lines.Add("  usage");
        lines.Add($"    tokens      {usage.InputTokens?.ToString(CultureInfo.InvariantCulture) ?? "?"} in / {usage.OutputTokens?.ToString(CultureInfo.InvariantCulture) ?? "?"} out");
        lines.Add("    cost        " + (!string.IsNullOrEmpty(usage.CostUsd) ? "$" + usage.CostUsd : "unknown (no trusted pricing)"));
        foreach (var estimated in usage.EstimatedFields.OrderBy(static pair => pair.Key, ScalarComparer.Instance))
        {
            AddWrapped(lines, $"    estimated   {estimated.Key}: {estimated.Value}", width);
        }

        var timing = manifest.Timing;
        if (timing.TotalMs is { } total)
        {
            lines.Add("  timing");
            lines.Add("    total       " + FormatRounded(total) + " ms");
            if (timing.FirstTokenMs is { } firstToken)
            {
                lines.Add("    first token " + FormatRounded(firstToken) + " ms");
            }

            foreach (var phase in timing.Phases.OrderBy(static pair => pair.Key, ScalarComparer.Instance))
            {
                lines.Add("    " + PadRightScalars(phase.Key, 12) + FormatRounded(phase.Value) + " ms");
            }
        }

        foreach (var note in manifest.Notes)
        {
            AddWrapped(lines, "  note: " + note, width);
        }

        if (manifest.Payloads is not null)
        {
            lines.Add("  payloads captured (redacted)");
        }

        return string.Join("\n", lines);
    }

    private static string FormatRounded(double value) => value.ToString("F0", CultureInfo.InvariantCulture);

    private static void AddWrapped(List<string> lines, string text, int width)
    {
        if (ScalarLength(text) <= width)
        {
            lines.Add(text);
            return;
        }

        var body = TrimLeadingWhitespace(text);
        var leading = ScalarLength(text) - ScalarLength(body);
        var initialIndent = new string(' ', leading);
        var subsequentIndent = initialIndent + "  ";
        lines.AddRange(Wrap(body, width, initialIndent, subsequentIndent));
    }

    private static IEnumerable<string> Wrap(string body, int width, string initialIndent, string subsequentIndent)
    {
        if (width <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), "Width must be greater than zero.");
        }

        // This mirrors textwrap.TextWrapper._wrap_chunks, retaining its hyphen and
        // long-word behavior while measuring Unicode scalar values rather than UTF-16 units.
        var chunks = SplitChunks(NormalizeWhitespace(ExpandTabs(body)));
        chunks.Reverse();
        var lines = new List<string>();
        while (chunks.Count != 0)
        {
            var current = new List<string>();
            var currentLength = 0;
            var indent = lines.Count == 0 ? initialIndent : subsequentIndent;
            var available = width - ScalarLength(indent);

            if (IsWhitespace(chunks[^1]) && lines.Count != 0)
            {
                chunks.RemoveAt(chunks.Count - 1);
            }

            while (chunks.Count != 0)
            {
                var chunk = chunks[^1];
                var length = ScalarLength(chunk);
                if (currentLength + length > available)
                {
                    break;
                }

                current.Add(chunk);
                chunks.RemoveAt(chunks.Count - 1);
                currentLength += length;
            }

            if (chunks.Count != 0 && ScalarLength(chunks[^1]) > available)
            {
                HandleLongWord(chunks, current, currentLength, available);
                currentLength = current.Sum(ScalarLength);
            }

            if (current.Count != 0 && IsWhitespace(current[^1]))
            {
                current.RemoveAt(current.Count - 1);
            }

            if (current.Count != 0)
            {
                lines.Add(indent + string.Concat(current));
            }
        }

        return lines;
    }

    private static void HandleLongWord(List<string> chunks, List<string> current, int currentLength, int available)
    {
        var space = available < 1 ? 1 : available - currentLength;
        if (space <= 0)
        {
            return;
        }

        var chunk = chunks[^1];
        var take = space;
        if (ScalarLength(chunk) > space)
        {
            var hyphen = LastHyphenBefore(chunk, space);
            if (hyphen > 0 && ContainsNonHyphenBefore(chunk, hyphen))
            {
                take = hyphen + 1;
            }
        }

        var prefix = TakeScalars(chunk, take);
        current.Add(prefix);
        chunks[^1] = chunk[prefix.Length..];
    }

    private static string ExpandTabs(string value)
    {
        var builder = new StringBuilder(value.Length);
        var column = 0;
        foreach (var rune in value.EnumerateRunes())
        {
            if (rune.Value == '\t')
            {
                var count = 8 - (column % 8);
                builder.Append(' ', count);
                column += count;
            }
            else
            {
                builder.Append(rune.ToString());
                column = rune.Value is '\n' or '\r' ? 0 : column + 1;
            }
        }

        return builder.ToString();
    }

    private static string NormalizeWhitespace(string value)
    {
        var builder = new StringBuilder(value.Length);
        foreach (var character in value)
        {
            builder.Append(character is '\t' or '\n' or '\v' or '\f' or '\r' ? ' ' : character);
        }

        return builder.ToString();
    }

    private static List<string> SplitChunks(string value)
    {
        // Port textwrap.wordsep_re instead of using .NET's \w/\s definitions. Python
        // recognizes only its six ASCII wrapping whitespace characters here, and its
        // qualified hyphen split depends on Python-word and Python-letter boundaries.
        var runes = value.EnumerateRunes().ToArray();
        var chunks = new List<string>();
        var index = 0;
        while (index < runes.Length)
        {
            var start = index;
            if (IsPythonWhitespace(runes[index]))
            {
                while (index < runes.Length && IsPythonWhitespace(runes[index]))
                {
                    index++;
                }

                chunks.Add(FromRunes(runes, start, index - start));
                continue;
            }

            if (StartsEmDash(runes, index))
            {
                while (index < runes.Length && runes[index].Value == '-')
                {
                    index++;
                }

                chunks.Add(FromRunes(runes, start, index - start));
                continue;
            }

            while (index < runes.Length)
            {
                index++;
                if (index == runes.Length || IsPythonWhitespace(runes[index]))
                {
                    break;
                }

                if (EndsQualifiedHyphen(runes, index) ||
                    (IsPythonWordPunctuation(runes[index - 1]) && StartsEmDash(runes, index)))
                {
                    break;
                }
            }

            chunks.Add(FromRunes(runes, start, index - start));
        }

        return chunks;
    }

    private static bool IsWhitespace(string value)
    {
        foreach (var rune in value.EnumerateRunes())
        {
            if (!IsPythonWhitespace(rune))
            {
                return false;
            }
        }

        return value.Length != 0;
    }

    private static bool IsPythonWhitespace(Rune rune) => rune.Value is ' ' or '\t' or '\n' or '\r' or '\v' or '\f';

    private static bool IsPythonWord(Rune rune) => rune.Value == '_' || Rune.IsLetterOrDigit(rune);

    private static bool IsPythonLetter(Rune rune) => IsPythonWord(rune) && !Rune.IsDigit(rune);

    private static bool IsPythonWordPunctuation(Rune rune) =>
        IsPythonWord(rune) || rune.Value is '!' or '"' or '\'' or '&' or '.' or ',' or '?';

    private static bool StartsEmDash(Rune[] runes, int index)
    {
        if (index == 0 || index >= runes.Length || runes[index].Value != '-' || !IsPythonWordPunctuation(runes[index - 1]))
        {
            return false;
        }

        var next = index;
        while (next < runes.Length && runes[next].Value == '-')
        {
            next++;
        }

        return next - index >= 2 && next < runes.Length && IsPythonWord(runes[next]);
    }

    private static bool EndsQualifiedHyphen(Rune[] runes, int afterHyphen)
    {
        var hyphen = afterHyphen - 1;
        if (hyphen < 0 || runes[hyphen].Value != '-')
        {
            return false;
        }

        var hasQualifiedPrefix =
            hyphen >= 2 && IsPythonLetter(runes[hyphen - 2]) && IsPythonLetter(runes[hyphen - 1]) ||
            hyphen >= 3 && IsPythonLetter(runes[hyphen - 3]) && runes[hyphen - 2].Value == '-' && IsPythonLetter(runes[hyphen - 1]);
        if (!hasQualifiedPrefix || afterHyphen >= runes.Length || !IsPythonLetter(runes[afterHyphen]))
        {
            return false;
        }

        return afterHyphen + 1 < runes.Length && IsPythonLetter(runes[afterHyphen + 1]) ||
               afterHyphen + 2 < runes.Length && runes[afterHyphen + 1].Value == '-' && IsPythonLetter(runes[afterHyphen + 2]);
    }

    private static string FromRunes(Rune[] runes, int start, int count)
    {
        var builder = new StringBuilder();
        for (var index = start; index < start + count; index++)
        {
            builder.Append(runes[index].ToString());
        }

        return builder.ToString();
    }

    private static int LastHyphenBefore(string value, int scalarLimit)
    {
        var index = 0;
        var last = -1;
        foreach (var rune in value.EnumerateRunes())
        {
            if (index >= scalarLimit)
            {
                break;
            }

            if (rune.Value == '-')
            {
                last = index;
            }

            index++;
        }

        return last;
    }

    private static bool ContainsNonHyphenBefore(string value, int scalarLimit)
    {
        var index = 0;
        foreach (var rune in value.EnumerateRunes())
        {
            if (index++ >= scalarLimit)
            {
                break;
            }

            if (rune.Value != '-')
            {
                return true;
            }
        }

        return false;
    }

    private static string TrimLeadingWhitespace(string value)
    {
        var index = 0;
        while (index < value.Length && char.IsWhiteSpace(value[index]))
        {
            index++;
        }

        return value[index..];
    }

    private static int ScalarLength(string value)
    {
        var length = 0;
        foreach (var _ in value.EnumerateRunes()) length++;
        return length;
    }

    private static string PadRightScalars(string value, int width)
    {
        var padding = width - ScalarLength(value);
        return padding <= 0 ? value : value + new string(' ', padding);
    }

    private static string TakeScalars(string value, int count)
    {
        if (count <= 0)
        {
            return string.Empty;
        }

        var index = 0;
        var taken = 0;
        foreach (var rune in value.EnumerateRunes())
        {
            if (taken++ == count)
            {
                break;
            }

            index += rune.Utf16SequenceLength;
        }

        return value[..index];
    }

    private sealed class ScalarComparer : IComparer<string>
    {
        internal static ScalarComparer Instance { get; } = new();

        public int Compare(string? left, string? right)
        {
            if (ReferenceEquals(left, right)) return 0;
            if (left is null) return -1;
            if (right is null) return 1;
            return JsonEquality.CompareCodePoints(left, right);
        }
    }

}
