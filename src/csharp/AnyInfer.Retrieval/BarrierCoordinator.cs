using System.Text.Json;
using AnyInfer.Json;

internal sealed class BarrierCoordinator
{
    private readonly object _gate = new();
    private readonly Dictionary<string, BarrierState> _states = new(StringComparer.Ordinal);
    private readonly CaptureOrder _order;

    internal BarrierCoordinator(CaptureOrder order) => _order = order;

    internal async Task WaitAsync(JsonElement gate, CancellationToken cancellationToken)
    {
        var readiness = gate.GetProperty("readiness").GetString()!;
        var release = gate.GetProperty("release").GetString()!;
        var cleanup = gate.GetProperty("finally_cleanup").GetString()!;
        var state = GetOrAdd(readiness, release, cleanup);
        state.Enter(_order.Next());
        try
        {
            await state.Release.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            state.Complete(_order.Next());
        }
    }

    internal void Register(JsonElement script, JsonElement step)
    {
        var gate = step.GetProperty("gate");
        _ = GetOrAdd(gate.GetProperty("readiness").GetString()!, gate.GetProperty("release").GetString()!,
            gate.GetProperty("finally_cleanup").GetString()!, script.GetProperty("id").GetString()!,
            step.GetProperty("ordinal").GetInt32(), script.GetProperty("instance").GetString()!);
    }

    internal Task WaitReadyAsync()
    {
        lock (_gate)
        {
            return Task.WhenAll(_states.Values.Select(static state => state.Ready.Task));
        }
    }

    internal void ReleaseAll()
    {
        lock (_gate)
        {
            foreach (var state in _states.Values)
            {
                state.Release.TrySetResult();
            }
        }
    }

    internal void MarkCallerCancellation()
    {
        lock (_gate)
        {
            foreach (var state in _states.Values) state.CallerCancelled ??= _order.Next();
        }
    }

    internal void MarkOperationFinally()
    {
        lock (_gate)
        {
            foreach (var state in _states.Values) state.OperationFinally ??= _order.Next();
        }
    }

    internal IReadOnlyList<JsonObject> Resources
    {
        get
        {
            lock (_gate)
            {
                return _states.Values.SelectMany(static state => state.Resources()).ToArray();
            }
        }
    }

    private BarrierState GetOrAdd(string readiness, string release, string cleanup, string? selectorId = null, int? stepOrdinal = null, string? instance = null)
    {
        lock (_gate)
        {
            if (!_states.TryGetValue(readiness, out var state))
            {
                state = new BarrierState(readiness, release, cleanup, selectorId, stepOrdinal, instance);
                _states.Add(readiness, state);
            }

            return state;
        }
    }

    private sealed class BarrierState
    {
        internal BarrierState(string readiness, string release, string cleanup, string? selectorId, int? stepOrdinal, string? instance)
        {
            Readiness = readiness;
            ReleaseId = release;
            Cleanup = cleanup;
            SelectorId = selectorId;
            StepOrdinal = stepOrdinal;
            Instance = instance;
        }

        internal string Readiness { get; }
        internal string ReleaseId { get; }
        internal string Cleanup { get; }
        internal string? SelectorId { get; }
        internal int? StepOrdinal { get; }
        internal string? Instance { get; }
        internal TaskCompletionSource Ready { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private long? Entered { get; set; }
        private long? Terminal { get; set; }
        internal long? CallerCancelled { get; set; }
        internal long? OperationFinally { get; set; }

        internal void Enter(long order)
        {
            Entered = order;
            Ready.TrySetResult();
        }

        internal void Complete(long order) => Terminal = order;

        internal IEnumerable<JsonObject> Resources()
        {
            if (Entered is not null) yield return Event("barrier_reached", Entered.Value);
            if (CallerCancelled is not null) yield return Event("caller_cancel_requested", CallerCancelled.Value);
            if (Terminal is not null) yield return Event("barrier_released", Terminal.Value);
            if (OperationFinally is not null) yield return Event("operation_finally", OperationFinally.Value);
        }

        private JsonObject Event(string type, long order) => FixtureJson.Object(
            ("type", FixtureJson.String(type)), ("order", FixtureJson.Integer(order)),
            ("selector_id", SelectorId is null ? FixtureJson.Null() : FixtureJson.String(SelectorId)),
            ("step_ordinal", StepOrdinal is null ? FixtureJson.Null() : FixtureJson.Integer(StepOrdinal.Value)),
            ("instance", Instance is null ? FixtureJson.Null() : FixtureJson.String(Instance)));
    }
}
