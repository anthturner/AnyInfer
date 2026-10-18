using System.Globalization;
using System.Text.RegularExpressions;

namespace AnyInfer.Routing;

internal static partial class RateLimitParsing
{
    [GeneratedRegex("(?<value>\\d+(?:\\.\\d+)?)(?<unit>ms|s|m|h)", RegexOptions.CultureInvariant)]
    private static partial Regex DurationPart();

    [GeneratedRegex("^(?<date>(?:\\d{4}-\\d{2}-\\d{2}|\\d{8}|\\d{4}-W\\d{2}-\\d|\\d{4}W\\d{2}\\d))(?<separator>(?:[\\uD800-\\uDBFF][\\uDC00-\\uDFFF]|[\\u0000-\\uD7FF\\uE000-\\uFFFF]))(?<hour>\\d{2})(?::?(?<minute>\\d{2}))?(?::?(?<second>\\d{2})(?:[.,](?<fraction>\\d+))?)?(?<offset>Z|(?<sign>[+-])(?<offsetHour>\\d{2})(?::?(?<offsetMinute>\\d{2}))?(?::?(?<offsetSecond>\\d{2})(?:[.,](?<offsetFraction>\\d+))?)?)$", RegexOptions.CultureInvariant)]
    private static partial Regex AwareIsoInstant();

    [GeneratedRegex("^(?<year>\\d{4})-?W(?<week>\\d{2})-?(?<day>\\d)$", RegexOptions.CultureInvariant)]
    private static partial Regex IsoWeekDate();

    internal static double? ParseResetSeconds(string? raw, TimeProvider timeProvider)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return null;
        }

        var text = raw.Trim();
        try
        {
            var seconds = double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);
            return seconds >= 0 ? seconds : null;
        }
        catch (FormatException)
        {
        }

        var matches = DurationPart().Matches(text);
        if (matches.Count > 0 && string.Concat(matches.Select(static match => match.Value)) == text)
        {
            var seconds = 0d;
            foreach (Match durationMatch in matches)
            {
                var value = double.Parse(durationMatch.Groups["value"].Value, NumberStyles.Float, CultureInfo.InvariantCulture);
                seconds += value * durationMatch.Groups["unit"].Value switch
                {
                    "ms" => 0.001,
                    "s" => 1,
                    "m" => 60,
                    "h" => 3600,
                    _ => throw new InvalidOperationException(),
                };
            }

            return seconds;
        }

        var match = AwareIsoInstant().Match(text);
        if (!match.Success)
        {
            return null;
        }

        if (!TryParseAwareIso(match, out var instant))
        {
            return null;
        }

        var result = (instant - timeProvider.GetUtcNow()).TotalSeconds;
        return result > 0 ? result : 0;
    }

    private static bool TryParseAwareIso(Match match, out DateTimeOffset instant)
    {
        instant = default;
        try
        {
            var date = ParseDate(match.Groups["date"].Value);
            var ticks = ParseFraction(match.Groups["fraction"].Value);
            var local = new DateTime(
                date.Year,
                date.Month,
                date.Day,
                ParseComponent(match, "hour"),
                ParseComponent(match, "minute"),
                ParseComponent(match, "second"),
                DateTimeKind.Unspecified).AddTicks(ticks);
            var offset = ParseOffset(match);
            instant = new DateTimeOffset(new DateTime(local.Ticks - offset.Ticks, DateTimeKind.Utc));
            return true;
        }
        catch (ArgumentOutOfRangeException)
        {
            return false;
        }
        catch (OverflowException)
        {
            return false;
        }
    }

    private static DateTime ParseDate(string value)
    {
        var week = IsoWeekDate().Match(value);
        if (week.Success)
        {
            var day = int.Parse(week.Groups["day"].Value, CultureInfo.InvariantCulture);
            return ISOWeek.ToDateTime(
                int.Parse(week.Groups["year"].Value, CultureInfo.InvariantCulture),
                int.Parse(week.Groups["week"].Value, CultureInfo.InvariantCulture),
                day is 7 ? DayOfWeek.Sunday : (DayOfWeek)day);
        }

        var digits = value.Replace("-", string.Empty, StringComparison.Ordinal);
        return new DateTime(
            int.Parse(digits[..4], CultureInfo.InvariantCulture),
            int.Parse(digits.Substring(4, 2), CultureInfo.InvariantCulture),
            int.Parse(digits.Substring(6, 2), CultureInfo.InvariantCulture));
    }

    private static TimeSpan ParseOffset(Match match)
    {
        if (match.Groups["offset"].Value == "Z")
        {
            return TimeSpan.Zero;
        }

        var offset = new TimeSpan(
            ParseComponent(match, "offsetHour"),
            ParseComponent(match, "offsetMinute"),
            ParseComponent(match, "offsetSecond")).Add(TimeSpan.FromTicks(ParseFraction(match.Groups["offsetFraction"].Value)));
        return match.Groups["sign"].Value == "-" ? -offset : offset;
    }

    private static int ParseComponent(Match match, string name) =>
        match.Groups[name].Success ? int.Parse(match.Groups[name].Value, CultureInfo.InvariantCulture) : 0;

    private static long ParseFraction(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return 0;
        }

        var microseconds = value.Length > 6 ? value[..6] : value.PadRight(6, '0');
        return long.Parse(microseconds, CultureInfo.InvariantCulture) * 10;
    }

    internal static long? ReadCount(IReadOnlyDictionary<string, string> headers, string name)
    {
        if (string.IsNullOrEmpty(name) || !TryGetHeader(headers, name, out var raw))
        {
            return null;
        }

        try
        {
            var value = double.Parse(raw.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture);
            if (double.IsNaN(value))
            {
                return null;
            }

            if (double.IsInfinity(value) || value > long.MaxValue || value < long.MinValue)
            {
                throw new OverflowException("The rate-limit header is outside the Int64 range.");
            }

            var count = checked((long)value);
            return count >= 0 ? count : null;
        }
        catch (FormatException)
        {
            return null;
        }
    }

    private static bool TryGetHeader(IReadOnlyDictionary<string, string> headers, string name, out string value)
    {
        if (headers.TryGetValue(name, out value!))
        {
            return true;
        }

        foreach (var header in headers)
        {
            if (string.Equals(header.Key, name, StringComparison.OrdinalIgnoreCase))
            {
                value = header.Value;
                return true;
            }
        }

        value = string.Empty;
        return false;
    }
}
