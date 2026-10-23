using System.Runtime.ExceptionServices;
using AnyInfer.Json;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Independent public controls for reflected tool binding and direct registry behavior.</summary>
public sealed class ToolBindingControlsTests
{
    [Fact]
    public async Task Reflection_binds_scalars_nullable_defaults_lists_and_maps()
    {
        var tool = Tool.From((Func<string, int?, bool, List<long>, IReadOnlyDictionary<string, string>, int, string>)Describe);
        var registry = new ToolRegistry([tool]);

        var result = await registry.DispatchAsync(new ToolCall("one", tool.Name, Object(
            ("name", new JsonString("Ada")),
            ("optional", JsonNull.Instance),
            ("enabled", new JsonBoolean(true)),
            ("sizes", new JsonArray([new JsonInteger(2), new JsonInteger(3)])),
            ("labels", Object(("region", new JsonString("west")))))));

        Assert.False(result.IsError);
        Assert.Equal("Ada:none:True:5:west:7", result.Content);
        Assert.True(tool.Spec.Parameters.TryGetValue("properties", out var properties));
        var declared = Assert.IsType<JsonObject>(properties);
        Assert.True(declared.TryGetValue("optional", out _));
        Assert.True(declared.TryGetValue("sizes", out _));
        Assert.True(declared.TryGetValue("labels", out _));
    }

    [Fact]
    public async Task Invalid_bound_values_become_errors_without_invoking_the_handler()
    {
        var calls = 0;
        var tool = Tool.From((Func<int, string>)(value =>
        {
            Interlocked.Increment(ref calls);
            return value.ToString();
        }));
        var registry = new ToolRegistry([tool]);

        foreach (var value in new JsonValue[]
        {
            new JsonNumber(1.5),
            new JsonString("1"),
            new JsonBoolean(true),
            new JsonInteger((System.Numerics.BigInteger)int.MaxValue + 1),
        })
        {
            var result = await registry.DispatchAsync(new ToolCall("bad", tool.Name, Object(("value", value))));
            Assert.True(result.IsError);
        }

        Assert.Equal(0, calls);
        Assert.Equal(4, registry.Dispatched);
    }

    [Fact]
    public async Task Injected_cancellation_and_params_are_not_model_bindable()
    {
        Interlocked.Exchange(ref _injectedCalls, 0);
        var tool = Tool.From((Func<string, CancellationToken, string[], string>)Injected);
        var registry = new ToolRegistry([tool]);

        Assert.True(tool.Spec.Parameters.TryGetValue("properties", out var properties));
        var declared = Assert.IsType<JsonObject>(properties);
        Assert.True(declared.TryGetValue("name", out _));
        Assert.False(declared.TryGetValue("token", out _));
        Assert.False(declared.TryGetValue("extras", out _));

        var tokenResult = await registry.DispatchAsync(new ToolCall("token", tool.Name, Object(
            ("name", new JsonString("Ada")),
            ("token", new JsonString("caller controlled")))));
        var paramsResult = await registry.DispatchAsync(new ToolCall("params", tool.Name, Object(
            ("name", new JsonString("Ada")),
            ("extras", new JsonArray([])))));

        Assert.True(tokenResult.IsError);
        Assert.True(paramsResult.IsError);
        Assert.Equal(0, Volatile.Read(ref _injectedCalls));
    }

    [Fact]
    public void Unsupported_reflected_delegates_are_rejected_at_registration()
    {
        RefInt byRef = RefValue;
        Action asyncVoid = AsyncVoid;
        Func<string, string> first = static value => value;
        Func<string, string> second = static value => value + "!";
        var multicast = first + second;

        Assert.Throws<ToolLoopException>(() => Tool.From(byRef));
        Assert.Throws<ToolLoopException>(() => Tool.From((Func<DateTime, string>)UnsupportedDate));
        Assert.Throws<ToolLoopException>(() => Tool.From(asyncVoid));
        Assert.Throws<ToolLoopException>(() => Tool.From(multicast));
    }

    [Fact]
    public async Task Task_and_value_task_results_are_awaited_before_registry_rendering()
    {
        var taskGate = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var valueTaskGate = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var task = Tool.From((Func<Task<string>>)(() => AwaitTask(taskGate)));
        var valueTask = Tool.From((Func<ValueTask<string>>)(() => AwaitValueTask(valueTaskGate)));
        var registry = new ToolRegistry([task, valueTask]);

        var pendingTask = registry.DispatchAsync(new ToolCall("task", task.Name, new JsonObject([])));
        Assert.False(pendingTask.IsCompleted);
        taskGate.SetResult("task-result");
        Assert.Equal("task-result", (await pendingTask).Content);

        var pendingValueTask = registry.DispatchAsync(new ToolCall("value-task", valueTask.Name, new JsonObject([])));
        Assert.False(pendingValueTask.IsCompleted);
        valueTaskGate.SetResult("value-task-result");
        Assert.Equal("value-task-result", (await pendingValueTask).Content);
    }

    [Fact]
    public async Task Foreign_cancellation_keeps_its_exact_instance_for_direct_and_registry_calls()
    {
        using var source = new CancellationTokenSource();
        var foreign = new OperationCanceledException("foreign", source.Token);
        var tool = Tool.From((Func<string>)(() => Throw(foreign)));
        var registry = new ToolRegistry([tool]);

        var direct = await Assert.ThrowsAsync<OperationCanceledException>(
            () => tool.CallAsync(new JsonObject([])).AsTask());
        var dispatched = await Assert.ThrowsAsync<OperationCanceledException>(
            () => registry.DispatchAsync(new ToolCall("cancel", tool.Name, new JsonObject([]))));

        Assert.Same(foreign, direct);
        Assert.Same(foreign, dispatched);
        Assert.Equal(source.Token, dispatched.CancellationToken);
        Assert.Equal(1, registry.Dispatched);
    }

    [Fact]
    public async Task Duplicate_names_keep_the_first_slot_and_concurrent_dispatch_counts_every_known_call()
    {
        var initial = new Tool(new ToolSpec("same", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("initial"));
        var replacement = new Tool(new ToolSpec("same", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("replacement"));
        var later = new Tool(new ToolSpec("later", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("later"));
        var registry = new ToolRegistry([initial, later, replacement]);

        Assert.Equal(["same", "later"], registry.Specs.Select(static spec => spec.Name));
        Assert.Equal("replacement", (await registry.DispatchAsync(new ToolCall("first", "same", new JsonObject([])))).Content);
        var dispatches = Enumerable.Range(0, 64)
            .Select(index => registry.DispatchAsync(new ToolCall(index.ToString(), "same", new JsonObject([]))));
        var results = await Task.WhenAll(dispatches);

        Assert.All(results, static result => Assert.Equal("replacement", result.Content));
        Assert.Equal(65, registry.Dispatched);
    }

    [Fact]
    public async Task Registry_renders_primitive_tagged_container_and_fallback_values_and_reports_cycles()
    {
        var primitive = Explicit("primitive", true);
        var tagged = Explicit("tagged", Object(("answer", new JsonInteger(42))));
        var container = Explicit("container", new Dictionary<string, object>
        {
            ["items"] = new List<int> { 1, 2 },
            ["enabled"] = false,
        });
        var fallback = Explicit("fallback", new DisplayValue());
        var cyclic = Explicit("cycle", Cyclic());
        var registry = new ToolRegistry([primitive, tagged, container, fallback, cyclic]);

        Assert.Equal("true", (await registry.DispatchAsync(new ToolCall("one", "primitive", new JsonObject([])))).Content);
        Assert.True(JsonEquality.TypeAwareEquals(
            Object(("answer", new JsonInteger(42))),
            ParseObject((await registry.DispatchAsync(new ToolCall("two", "tagged", new JsonObject([])))).Content)));
        Assert.True(JsonEquality.TypeAwareEquals(
            Object(
                ("items", new JsonArray([new JsonInteger(1), new JsonInteger(2)])),
                ("enabled", new JsonBoolean(false))),
            ParseObject((await registry.DispatchAsync(new ToolCall("three", "container", new JsonObject([])))).Content)));
        Assert.Equal("display fallback", (await registry.DispatchAsync(new ToolCall("four", "fallback", new JsonObject([])))).Content);
        var cycle = await registry.DispatchAsync(new ToolCall("five", "cycle", new JsonObject([])));
        Assert.True(cycle.IsError);
        Assert.StartsWith("InvalidOperationException: Cyclic tool return value.", cycle.Content);
    }

    private delegate void RefInt(ref int value);
    private static int _injectedCalls;

    private static string Describe(
        string name,
        int? optional,
        bool enabled,
        List<long> sizes,
        IReadOnlyDictionary<string, string> labels,
        int count = 7) =>
        $"{name}:{optional?.ToString() ?? "none"}:{enabled}:{sizes.Sum()}:{labels["region"]}:{count}";

    private static void RefValue(ref int value) => value++;
    private static string UnsupportedDate(DateTime value) => value.ToString("O");
    private static async void AsyncVoid() => await Task.Yield();
    private static string Injected(string name, CancellationToken token, params string[] extras)
    {
        Interlocked.Increment(ref _injectedCalls);
        return $"{name}:{token.CanBeCanceled}:{extras.Length}";
    }
    private static async Task<string> AwaitTask(TaskCompletionSource<string> gate) => await gate.Task;
    private static async ValueTask<string> AwaitValueTask(TaskCompletionSource<string> gate) => await gate.Task;
    private static string Throw(OperationCanceledException exception)
    {
        ExceptionDispatchInfo.Capture(exception).Throw();
        throw new InvalidOperationException("unreachable");
    }

    private static Tool Explicit(string name, object? result) =>
        new(new ToolSpec(name, "", new JsonObject([])), (_, _) => ValueTask.FromResult(result));

    private static List<object> Cyclic()
    {
        var values = new List<object>();
        values.Add(values);
        return values;
    }

    private static JsonObject Object(params (string Name, JsonValue Value)[] values) =>
        new(values.Select(static value => new JsonProperty(value.Name, value.Value)));

    private static JsonObject ParseObject(string text) =>
        Assert.IsType<JsonObject>(JsonReader.Read(text));

    private sealed class DisplayValue
    {
        public override string ToString() => "display fallback";
    }
}
