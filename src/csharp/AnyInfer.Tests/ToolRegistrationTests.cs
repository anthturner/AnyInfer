using System.Numerics;
using AnyInfer.Json;
using Xunit;

namespace AnyInfer.Tests;

/// <summary>Public controls for native tool registration, binding, and dispatch isolation.</summary>
public sealed class ToolRegistrationTests
{
    [Fact]
    public async Task Explicit_json_handler_preserves_direct_failures_and_registry_makes_them_results()
    {
        var failure = new InvalidOperationException("handler failed");
        var tool = new Tool(new ToolSpec("fail", "", new JsonObject([])), (_, _) => ValueTask.FromException<object?>(failure));
        await Assert.ThrowsAsync<InvalidOperationException>(async () => await tool.CallAsync(new JsonObject([])));
        var result = await new ToolRegistry([tool]).DispatchAsync(new ToolCall("one", "fail", new JsonObject([])));

        Assert.True(result.IsError);
        Assert.Equal("InvalidOperationException: handler failed", result.Content);
    }

    [Fact]
    public async Task Reflection_declares_supported_shapes_omits_token_and_params_and_binds_defaults()
    {
        var tool = Tool.From((Func<string, int, CancellationToken, string>)Describe);
        var paramsTool = Tool.From((Func<string[], string>)Params);
        var registry = new ToolRegistry([tool, paramsTool]);
        var result = await registry.DispatchAsync(new ToolCall("a", "Describe", Object(("name", new JsonString("Ada")))));
        var paramsResult = await registry.DispatchAsync(new ToolCall("b", "Params", new JsonObject([])));

        Assert.Equal("Ada:7", result.Content);
        Assert.Equal("0", paramsResult.Content);
        Assert.True(tool.Spec.Parameters.TryGetValue("properties", out var properties));
        var objectProperties = Assert.IsType<JsonObject>(properties);
        Assert.True(objectProperties.TryGetValue("name", out _));
        Assert.True(objectProperties.TryGetValue("count", out _));
        Assert.False(objectProperties.TryGetValue("cancellationToken", out _));
        Assert.False(paramsTool.Spec.Parameters.TryGetValue("values", out _));
    }

    [Fact]
    public async Task Registry_keeps_first_slot_for_duplicate_name_counts_known_dispatches_and_preserves_cancellation()
    {
        var first = new Tool(new ToolSpec("same", "first", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("first"));
        var replacement = new Tool(new ToolSpec("same", "replacement", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>("replacement"));
        var cancelled = new Tool(new ToolSpec("cancel", "", new JsonObject([])), (_, token) => ValueTask.FromException<object?>(new OperationCanceledException(token)));
        var registry = new ToolRegistry([first, replacement, cancelled]);

        Assert.Equal(["same", "cancel"], registry.Specs.Select(static spec => spec.Name));
        Assert.Equal("replacement", (await registry.DispatchAsync(new ToolCall("one", "same", new JsonObject([])))).Content);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => registry.DispatchAsync(new ToolCall("two", "cancel", new JsonObject([]))));
        await Assert.ThrowsAsync<ToolLoopException>(() => registry.DispatchAsync(new ToolCall("three", "missing", new JsonObject([]))));
        Assert.Equal(2, registry.Dispatched);
    }

    [Fact]
    public async Task Return_paths_preserve_sync_and_awaitable_scalars_and_turn_cycles_into_errors()
    {
        var huge = Tool.From((Func<BigInteger>)Huge);
        var scalar = Tool.From((Func<int>)Scalar);
        var task = Tool.From((Func<Task<long>>)TaskValue);
        var valueTask = Tool.From((Func<ValueTask<string>>)ValueTaskValue);
        var cyclic = new Tool(new ToolSpec("cycle", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>(Cycle()));
        var registry = new ToolRegistry([huge, scalar, task, valueTask, cyclic]);

        Assert.Equal("9223372036854775808", (await registry.DispatchAsync(new ToolCall("one", "Huge", new JsonObject([])))).Content);
        Assert.Equal("12", (await registry.DispatchAsync(new ToolCall("two", "Scalar", new JsonObject([])))).Content);
        Assert.Equal("34", (await registry.DispatchAsync(new ToolCall("three", "TaskValue", new JsonObject([])))).Content);
        Assert.Equal("async", (await registry.DispatchAsync(new ToolCall("four", "ValueTaskValue", new JsonObject([])))).Content);
        var failed = await registry.DispatchAsync(new ToolCall("five", "cycle", new JsonObject([])));
        Assert.True(failed.IsError);
        Assert.StartsWith("InvalidOperationException:", failed.Content);
    }

    [Fact]
    public async Task Nested_nulls_in_json_compatible_returns_remain_json_nulls()
    {
        var array = new Tool(new ToolSpec("array", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>(new List<object?> { "x", null }));
        var map = new Tool(new ToolSpec("map", "", new JsonObject([])), (_, _) => ValueTask.FromResult<object?>(new Dictionary<string, object?> { ["value"] = null }));
        var registry = new ToolRegistry([array, map]);

        Assert.Equal("[\"x\",null]", (await registry.DispatchAsync(new ToolCall("one", "array", new JsonObject([])))).Content);
        Assert.Equal("{\"value\":null}", (await registry.DispatchAsync(new ToolCall("two", "map", new JsonObject([])))).Content);
    }

    private static string Describe(string name, int count = 7, CancellationToken cancellationToken = default) => name + ":" + count;
    private static string Params(params string[] values) => values.Length.ToString();
    private static BigInteger Huge() => BigInteger.One << 63;
    private static int Scalar() => 12;
    private static Task<long> TaskValue() => Task.FromResult(34L);
    private static ValueTask<string> ValueTaskValue() => ValueTask.FromResult("async");
    private static List<object> Cycle() { var values = new List<object>(); values.Add(values); return values; }
    private static JsonObject Object(params (string Name, JsonValue Value)[] values) => new(values.Select(static value => new JsonProperty(value.Name, value.Value)));
}
