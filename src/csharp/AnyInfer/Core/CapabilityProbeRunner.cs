using AnyInfer.Capabilities;
using AnyInfer.Internal;
using AnyInfer.Json;
using AnyInfer.Providers;
using AnyInfer.Schema;

namespace AnyInfer.Core;

/// <summary>Runs one direct, feature-specific adapter probe without routing or repair.</summary>
internal static class CapabilityProbeRunner
{
    internal static async Task<(FeatureProbe Probe, Usage Usage)> RunAsync(
        IProviderAdapter adapter,
        ResolvedProvider resolved,
        Feature feature,
        double timeoutS,
        AsyncClient owner,
        Client? syncOwner,
        CancellationToken operationToken,
        CancellationToken callerIdentity,
        Action<Exception> onSignalFailure)
    {
        ArgumentNullException.ThrowIfNull(adapter);
        ArgumentNullException.ThrowIfNull(resolved);
        ArgumentNullException.ThrowIfNull(owner);
        ArgumentNullException.ThrowIfNull(onSignalFailure);
        ProbeFeatureLease.ValidateTimeout(timeoutS);

        var mechanism = CapabilityProbes.MechanismFor(feature);
        var schema = mechanism is null ? null : new SchemaSpec(CapabilityProbes.ProbeSchema, "capability_probe");
        var normalized = new NormalizedRequest(
            [Message.User(CapabilityProbes.ProbePrompt(feature))],
            new Sampling(temperature: 0, maxOutputTokens: CapabilityProbes.ProbeMaxOutputTokens),
            schema,
            RepairBudget: 0,
            TimeoutS: timeoutS,
            MaxResponseBytes: 1_048_576,
            Stream: feature == Feature.Streaming,
            SchemaProfile: SchemaExecutionProfile.ModernSdk,
            SchemaValidation: null);
        var forced = resolved with
        {
            Capabilities = new StructuredOutputProfile(
                Grammar: feature == Feature.Grammar,
                JsonSchema: feature == Feature.JsonSchema,
                JsonMode: feature == Feature.JsonMode),
        };
        var tools = feature == Feature.Tools ? new[] { CapabilityProbes.ProbeTool } : Array.Empty<ToolSpec>();
        var wire = RequestNormalizer.CreateWireRequest(normalized, forced, tools: tools, toolChoice: feature == Feature.Tools ? "required" : "auto");

        var lease = new ProbeFeatureLease(timeoutS, owner, syncOwner, operationToken, callerIdentity, onSignalFailure);
        var leaseFinalized = false;
        using var context = AsyncExecutionContext.Push(owner, syncOwner);
        using var identity = CancellationIdentityContext.Push(lease.Token, callerIdentity);

        var text = new System.Text.StringBuilder();
        var contentEvents = 0;
        var toolCalled = false;
        Usage? usage = null;
        ProviderException? providerFailure = null;
        var ownedTimeout = false;
        IAsyncEnumerator<AdapterEvent>? iterator = null;

        try
        {
            try
            {
                try
                {
                    lease.ThrowIfOperationOrCallerCancelled();
                    var events = adapter.GenerateAsync(wire, lease.Token);
                    iterator = events.GetAsyncEnumerator(lease.Token);
                    while (await iterator.MoveNextAsync().ConfigureAwait(false))
                    {
                        switch (iterator.Current)
                        {
                            case AdapterTextDelta delta:
                                contentEvents++;
                                text.Append(delta.Text);
                                break;
                            case AdapterToolCallDelta:
                                contentEvents++;
                                toolCalled = true;
                                break;
                            case AdapterUsage usageEvent:
                                usage = OverlayUsage(usage, usageEvent.Usage);
                                break;
                            case AdapterFinal { Usage: { } finalUsage }:
                                usage = OverlayUsage(usage, finalUsage);
                                break;
                        }
                    }
                }
                catch (ProviderException exception)
                {
                    providerFailure = exception;
                }
                catch (OperationCanceledException exception) when (lease.IsOwnedTimeout(exception))
                {
                    ownedTimeout = true;
                }
            }
            finally
            {
                if (iterator is not null)
                {
                    await iterator.DisposeAsync().ConfigureAwait(false);
                }
            }

            leaseFinalized = true;
            await lease.DisposeAsync().ConfigureAwait(false);
            lease.ThrowIfOperationOrCallerCancelled();

            var spent = usage ?? new Usage();

            if (providerFailure is not null)
            {
                return (new FeatureProbe(feature, ProbeOutcome.Unsupported, providerFailure.Detail ?? providerFailure.Message), spent);
            }

            if (ownedTimeout || lease.TimeoutOrigin)
            {
                return (new FeatureProbe(feature, ProbeOutcome.Inconclusive, "the probe timed out"), spent);
            }

            var probe = await JudgeAsync(feature, text.ToString(), contentEvents, toolCalled, schema, lease.Token).ConfigureAwait(false);
            lease.ThrowIfOperationOrCallerCancelled();
            return (probe, spent);
        }
        finally
        {
            if (!leaseFinalized)
            {
                await lease.DisposeAsync().ConfigureAwait(false);
            }
        }
    }

    private static async Task<FeatureProbe> JudgeAsync(
        Feature feature,
        string text,
        int contentEvents,
        bool toolCalled,
        SchemaSpec? schema,
        CancellationToken cancellationToken)
    {
        if (feature == Feature.Tools)
        {
            return toolCalled
                ? new FeatureProbe(feature, ProbeOutcome.Supported)
                : new FeatureProbe(feature, ProbeOutcome.Inconclusive, "the response did not contain a tool call");
        }

        if (feature == Feature.Streaming)
        {
            return contentEvents > 1
                ? new FeatureProbe(feature, ProbeOutcome.Supported)
                : new FeatureProbe(feature, ProbeOutcome.Inconclusive, "the response did not contain multiple content events");
        }

        var extracted = ResponseExtractor.ExtractModern(text);
        if (extracted.Value is null)
        {
            return new FeatureProbe(feature, ProbeOutcome.Inconclusive, extracted.Failure?.Message ?? "the response did not contain JSON");
        }

        if (feature == Feature.JsonMode)
        {
            return new FeatureProbe(feature, ProbeOutcome.Supported);
        }

        var validation = await SchemaValidator.ValidateAsync(extracted.Value, schema!, cancellationToken: cancellationToken).ConfigureAwait(false);
        return validation.IsValid
            ? new FeatureProbe(feature, ProbeOutcome.Supported)
            : new FeatureProbe(feature, ProbeOutcome.Inconclusive, "the JSON response did not match the probe schema");
    }

    private static Usage? OverlayUsage(Usage? existing, Usage? overlay) => overlay is null
        ? existing
        : new Usage(
            overlay.InputTokens ?? existing?.InputTokens,
            overlay.OutputTokens ?? existing?.OutputTokens,
            overlay.TotalTokens ?? existing?.TotalTokens,
            overlay.CacheReadTokens ?? existing?.CacheReadTokens,
            overlay.CacheWriteTokens ?? existing?.CacheWriteTokens,
            overlay.ReasoningTokens ?? existing?.ReasoningTokens);

}
