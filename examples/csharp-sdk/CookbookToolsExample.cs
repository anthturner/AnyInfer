using AnyInfer.Capabilities;

namespace AnyInfer.Examples;

/// <summary>
/// An order-support assistant: two registered tools with typed arguments run in the SDK's bounded loop,
/// with the caller's cancellation token passed into each handler and handler failures returned to the model.
/// </summary>
public static class CookbookToolsExample
{
    /// <summary>Answers one customer question, letting the model look up orders and quote refunds.</summary>
    /// <param name="providers">The provider instances the target names.</param>
    /// <param name="target">The <c>provider:model</c> target that runs every round.</param>
    /// <param name="orders">The application's order store; the handlers are its only path to order data.</param>
    /// <param name="question">The customer's question.</param>
    /// <param name="cancellationToken">Cancels the loop, including a handler that is running.</param>
    /// <returns>The final answer, every tool use, and usage totals across all rounds.</returns>
    public static async Task<CookbookAssistantReply> AnswerAsync(
        IEnumerable<ProviderSettings> providers,
        string target,
        ICookbookOrderStore orders,
        string question,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(orders);
        var toolUses = new List<string>();

        async Task<Dictionary<string, object>> LookupOrder(string orderId, CancellationToken token)
        {
            toolUses.Add($"lookup_order {orderId}");
            var order = await orders.FindAsync(orderId, token)
                ?? throw new KeyNotFoundException($"Order {orderId} does not exist.");
            return new Dictionary<string, object>
            {
                ["order_id"] = order.Id,
                ["status"] = order.Status,
                ["units"] = order.Units,
                ["unit_price_cents"] = order.UnitPriceCents,
            };
        }

        async Task<string> QuoteRefund(string orderId, int units, bool includeShipping = false, CancellationToken token = default)
        {
            toolUses.Add($"quote_refund {orderId} x{units}{(includeShipping ? " +shipping" : "")}");
            var order = await orders.FindAsync(orderId, token)
                ?? throw new KeyNotFoundException($"Order {orderId} does not exist.");
            if (units < 1 || units > order.Units)
            {
                throw new ArgumentOutOfRangeException(nameof(units), $"Order {orderId} has {order.Units} unit(s).");
            }

            var cents = units * order.UnitPriceCents + (includeShipping ? order.ShippingCents : 0);
            return $"Refund for {units} unit(s) of {orderId}: {cents / 100m:0.00} USD.";
        }

        Tool[] tools =
        [
            Tool.From(LookupOrder, name: "lookup_order", description: "Looks up one order's status, unit count and unit price."),
            Tool.From(QuoteRefund, name: "quote_refund", description: "Quotes a refund for some units of one order."),
        ];

        // The ledger totals every round; the returned generation describes only the final one.
        var ledger = new SpendLedger();
        await using var client = new AsyncClient(providers, ledger: ledger);
        try
        {
            var generation = await client.RunToolsAsync(
                [
                    Message.System("You are an order-support assistant. Use the tools for every order fact; never guess."),
                    Message.User(question),
                ],
                tools,
                target: target,
                sampling: new Sampling(temperature: 0),
                maxRounds: 4,
                cancellationToken: cancellationToken);
            return new CookbookAssistantReply(generation.Text, toolUses, ledger.Totals(), null);
        }
        catch (ToolLoopException failure)
        {
            // An unregistered tool or an exhausted round budget; nothing more is sent.
            return new CookbookAssistantReply(null, toolUses, ledger.Totals(), failure);
        }
    }
}

/// <summary>The application's order data, as the tool handlers see it.</summary>
public interface ICookbookOrderStore
{
    /// <summary>Finds one order.</summary>
    /// <param name="orderId">The order identifier the model asked about.</param>
    /// <param name="cancellationToken">The tool call's cancellation token.</param>
    /// <returns>The order, or <see langword="null"/> when it does not exist.</returns>
    Task<CookbookOrder?> FindAsync(string orderId, CancellationToken cancellationToken);
}

/// <summary>An in-memory order store for the sample.</summary>
/// <param name="orders">The orders the store holds.</param>
public sealed class CookbookInMemoryOrders(params CookbookOrder[] orders) : ICookbookOrderStore
{
    private readonly Dictionary<string, CookbookOrder> _orders = orders.ToDictionary(static order => order.Id, StringComparer.Ordinal);

    /// <inheritdoc />
    public Task<CookbookOrder?> FindAsync(string orderId, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(_orders.GetValueOrDefault(orderId));
    }
}

/// <summary>One order.</summary>
/// <param name="Id">The order identifier.</param>
/// <param name="Status">The fulfilment status.</param>
/// <param name="Units">The number of units ordered.</param>
/// <param name="UnitPriceCents">The unit price in cents.</param>
/// <param name="ShippingCents">The shipping charge in cents.</param>
public sealed record CookbookOrder(string Id, string Status, int Units, int UnitPriceCents, int ShippingCents);

/// <summary>The assistant's answer and what it took to produce it.</summary>
/// <param name="Text">The final answer, or <see langword="null"/> when the loop failed.</param>
/// <param name="ToolUses">Each handler invocation, in order, including ones that failed.</param>
/// <param name="Totals">Requests and reported tokens across every round.</param>
/// <param name="Failure">The tool-loop failure, when the loop did not produce an answer.</param>
public sealed record CookbookAssistantReply(
    string? Text,
    IReadOnlyList<string> ToolUses,
    SpendTotals Totals,
    ToolLoopException? Failure);
