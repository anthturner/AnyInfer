using System.Text;
using System.Text.Json;
using AnyInfer.Credentials;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public credential-reference and diagnostic-redaction behavior.</summary>
public sealed class CredentialsTests
{
    [Fact]
    public async Task Resolver_chain_handles_blank_literal_environment_and_custom_references_without_fallback()
    {
        var environmentName = $"ANYINFER_SDK2_{Guid.NewGuid():N}";
        Environment.SetEnvironmentVariable(environmentName, "from-environment");
        var custom = new RecordingResolver("vault://", "from-custom");
        var chain = new ResolverChain([new EnvResolver(), new LiteralResolver(), custom]);

        try
        {
            Assert.Null(await chain.ResolveAsync("   "));
            Assert.Equal("literal-value", await chain.ResolveAsync("literal-value"));
            Assert.Equal("from-environment", await chain.ResolveAsync($"env://{environmentName}"));
            Assert.Equal("from-custom", await chain.ResolveAsync("vault://sdk2/key"));
            Assert.Equal(1, custom.ResolveCalls);
        }
        finally
        {
            Environment.SetEnvironmentVariable(environmentName, null);
        }
    }

    [Theory]
    [InlineData("ENV://{0}")]
    [InlineData("CREDENTIAL://system/sdk2")]
    public async Task Uppercase_ascii_builtin_credential_references_never_fall_back_to_literals(string referenceTemplate)
    {
        var environmentName = $"ANYINFER_SDK2_{Guid.NewGuid():N}";
        Environment.SetEnvironmentVariable(environmentName, "lowercase-only");
        try
        {
            var chain = ResolverChain.CreateDefault();
            Assert.Equal("lowercase-only", await chain.ResolveAsync($"env://{environmentName}"));
            await Assert.ThrowsAsync<CredentialException>(async () =>
                await chain.ResolveAsync(string.Format(referenceTemplate, environmentName)));
        }
        finally
        {
            Environment.SetEnvironmentVariable(environmentName, null);
        }
    }

    [Theory]
    [InlineData("βvault://literal-value")]
    [InlineData("vaült://literal-value")]
    public async Task Unicode_letter_uri_shaped_values_remain_literal_credentials(string reference) =>
        Assert.Equal(reference, await ResolverChain.CreateDefault().ResolveAsync(reference));

    [Theory]
    [InlineData("env:/MALFORMED")]
    [InlineData("vault://unconfigured/key")]
    public async Task Malformed_or_unhandled_reference_never_falls_back_to_a_literal(string reference)
    {
        var chain = ResolverChain.CreateDefault();

        await Assert.ThrowsAsync<CredentialException>(async () => await chain.ResolveAsync(reference));
    }

    [Fact]
    public async Task Keyring_reference_is_a_controlled_unavailable_credential_path()
    {
        var failure = await Assert.ThrowsAsync<CredentialException>(async () =>
            await ResolverChain.CreateDefault().ResolveAsync("credential://system/sdk2"));

        Assert.Equal("credential", failure.Category);
        Assert.Equal("configure", failure.Phase);
        Assert.NotNull(failure.Hint);
    }

    [Fact]
    public async Task Resolver_cancellation_propagates_the_original_operation_canceled_exception()
    {
        var expected = new OperationCanceledException("resolver cancellation");
        var chain = new ResolverChain([new ThrowingResolver("cancel://", expected)]);

        var actual = await Assert.ThrowsAsync<OperationCanceledException>(async () =>
            await chain.ResolveAsync("cancel://sdk2"));

        Assert.Same(expected, actual);
    }

    [Fact]
    public async Task Resolved_secrets_are_removed_from_error_rendering_and_bounded_snapshots()
    {
        var secret = $"sdk2-\"quoted-Å😀-{Guid.NewGuid():N}";
        var chain = new ResolverChain([new RecordingResolver("vault://", secret)]);
        Assert.Equal(secret, await chain.ResolveAsync("vault://redaction"));

        var jsonEscaped = JsonSerializer.Serialize(secret)[1..^1];
        var pythonJsonEscaped = PythonEnsureAsciiJsonContents(secret);
        var urlEscaped = Uri.EscapeDataString(secret);
        var base64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(secret));
        var longDetail = string.Concat(Enumerable.Repeat($"{secret}|{jsonEscaped}|{urlEscaped}|{base64}|", 30));
        var native = new InvalidOperationException($"native {secret}");
        var failure = new ProviderException(
            $"message {secret} {jsonEscaped} {urlEscaped} {base64}",
            "transport",
            true,
            "generate",
            detail: longDetail,
            hint: $"hint {secret}",
            nativeInner: native);
        var snapshot = failure.Snapshot();

        Assert.Same(native, failure.NativeInner);
        Assert.True(snapshot.Detail!.Length <= 512);
        foreach (var spelling in new[] { secret, jsonEscaped, pythonJsonEscaped, urlEscaped, base64 })
        {
            Assert.DoesNotContain(spelling, failure.Message, StringComparison.Ordinal);
            Assert.DoesNotContain(spelling, failure.Detail!, StringComparison.Ordinal);
            Assert.DoesNotContain(spelling, failure.Hint!, StringComparison.Ordinal);
            Assert.DoesNotContain(spelling, failure.ToString(), StringComparison.Ordinal);
            Assert.DoesNotContain(spelling, snapshot.Detail!, StringComparison.Ordinal);
        }

        Assert.Equal(string.Empty, Redaction.Redact(null));
    }

    [Fact]
    public void Redaction_counts_unicode_scalars_and_never_splits_a_surrogate_pair_when_bounding_detail()
    {
        var underSixScalars = "😀a😀b";
        var sixScalars = "😀a😀b😀c";
        Redaction.RegisterSecret(underSixScalars);
        Redaction.RegisterSecret(sixScalars);

        Assert.Equal(underSixScalars, Redaction.Redact(underSixScalars));
        Assert.DoesNotContain(sixScalars, Redaction.Redact(sixScalars), StringComparison.Ordinal);

        var failure = new ProviderException("bounded", "transport", true, "generate", detail: string.Concat(Enumerable.Repeat("😀", 600)));
        var detail = Assert.IsType<string>(failure.Detail);
        Assert.Equal(512, detail.EnumerateRunes().Count());
        Assert.Equal('…', detail[^1]);
        Assert.DoesNotContain('\uFFFD', detail);
    }

    [Fact]
    public void Config_exception_safe_rendering_excludes_unregistered_native_path_while_preserving_identity()
    {
        var marker = $"unregistered-config-native-path-{Guid.NewGuid():N}";
        var native = new FileNotFoundException($"missing {marker}", marker);
        var failure = new ConfigException("Configuration material could not be read.", nativeInner: native);

        Assert.Same(native, failure.NativeInner);
        Assert.Same(native, failure.InnerException);
        Assert.DoesNotContain(marker, failure.ToString(), StringComparison.Ordinal);
        Assert.DoesNotContain(marker, failure.Snapshot().ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Error_safe_fields_and_message_only_snapshots_redact_registered_secrets()
    {
        var secret = $"sdk2-safe-Å😀-{Guid.NewGuid():N}";
        var chain = new ResolverChain([new RecordingResolver("vault://", secret)]);
        await chain.ResolveAsync("vault://safe-fields");

        var config = new ConfigException($"configuration {secret}");
        var credential = new CredentialException($"credential {secret}");
        foreach (var failure in new AnyInferException[] { config, credential })
        {
            Assert.Null(failure.Detail);
            var snapshot = failure.Snapshot();
            Assert.NotNull(snapshot.Detail);
            Assert.True(snapshot.Detail!.Length <= 512);
            AssertNoSecret(secret, failure.Message, snapshot.Detail, failure.ToString());
        }

        var provider = new ProviderException(
            "safe message",
            secret,
            true,
            secret,
            provider: secret,
            detail: "safe detail");
        var providerSnapshot = provider.Snapshot();
        AssertNoSecret(secret, provider.Category, provider.Phase, provider.Provider, providerSnapshot.Provider, providerSnapshot.Phase, provider.ToString());
    }

    [Fact]
    public void Frozen_provider_error_classifier_preserves_typed_category_metadata_and_native_inner()
    {
        var native = new InvalidOperationException("native");
        var timeout = ProviderException.Create(
            "timeout",
            "timeout",
            true,
            "stream",
            retryAfterS: 2.5,
            httpStatus: 504,
            provider: "alpha",
            detail: "bounded",
            hint: "retry later",
            nativeInner: native);

        var typed = Assert.IsType<TransportException>(timeout);
        Assert.Equal("timeout", typed.Category);
        Assert.True(typed.Retryable);
        Assert.Equal("stream", typed.Phase);
        Assert.Equal(2.5, typed.RetryAfterS);
        Assert.Equal(504, typed.HttpStatus);
        Assert.Equal("alpha", typed.Provider);
        Assert.Equal("bounded", typed.Detail);
        Assert.Equal("retry later", typed.Hint);
        Assert.Same(native, typed.NativeInner);

        var nullable = ProviderException.Create("plain", "transport", false, null);
        Assert.IsType<TransportException>(nullable);
        Assert.Null(nullable.Phase);
        Assert.Null(nullable.RetryAfterS);
        Assert.Null(nullable.HttpStatus);
        Assert.Null(nullable.Provider);
        Assert.Null(nullable.Detail);
        Assert.Null(nullable.Hint);
        Assert.Null(nullable.NativeInner);
    }

    [Theory]
    [InlineData("auth", typeof(AuthException))]
    [InlineData("rate_limit", typeof(RateLimitException))]
    [InlineData("model_not_found", typeof(ModelNotFoundException))]
    [InlineData("context_length", typeof(ContextLengthException))]
    [InlineData("transport", typeof(TransportException))]
    [InlineData("stream_protocol", typeof(StreamProtocolException))]
    [InlineData("provider_unavailable", typeof(ProviderUnavailableException))]
    [InlineData("unsupported_input", typeof(UnsupportedInputException))]
    public void Frozen_provider_error_classifier_maps_each_declared_typed_category(string category, Type expectedType)
    {
        var classified = ProviderException.Create("classified", category, retryable: false, phase: "generate");

        Assert.IsType(expectedType, classified);
        Assert.Equal(category, classified.Category);
    }

    private static void AssertNoSecret(string secret, params string?[] fields)
    {
        foreach (var field in fields.Where(static field => field is not null))
        {
            Assert.DoesNotContain(secret, field!, StringComparison.Ordinal);
        }
    }

    private static string PythonEnsureAsciiJsonContents(string value)
    {
        var output = new StringBuilder();
        foreach (var rune in value.EnumerateRunes())
        {
            switch (rune.Value)
            {
                case (int)'"': output.Append("\\\""); break;
                case (int)'\\': output.Append("\\\\"); break;
                case >= 0x20 and <= 0x7e: output.Append(rune.ToString()); break;
                case <= 0xffff: output.Append($"\\u{rune.Value:x4}"); break;
                default:
                    var scalar = rune.Value - 0x10000;
                    output.Append($"\\u{((scalar >> 10) + 0xd800):x4}\\u{((scalar & 0x3ff) + 0xdc00):x4}");
                    break;
            }
        }

        return output.ToString();
    }

    private sealed class RecordingResolver : ICredentialResolver
    {
        private readonly string _prefix;
        private readonly string _value;

        internal RecordingResolver(string prefix, string value)
        {
            _prefix = prefix;
            _value = value;
        }

        internal int ResolveCalls { get; private set; }

        public bool Handles(string reference) => reference.StartsWith(_prefix, StringComparison.Ordinal);

        public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            ResolveCalls++;
            return ValueTask.FromResult(_value);
        }
    }

    private sealed class ThrowingResolver : ICredentialResolver
    {
        private readonly string _prefix;
        private readonly OperationCanceledException _failure;

        internal ThrowingResolver(string prefix, OperationCanceledException failure)
        {
            _prefix = prefix;
            _failure = failure;
        }

        public bool Handles(string reference) => reference.StartsWith(_prefix, StringComparison.Ordinal);

        public ValueTask<string> ResolveAsync(string reference, CancellationToken cancellationToken = default) =>
            ValueTask.FromException<string>(_failure);
    }
}
