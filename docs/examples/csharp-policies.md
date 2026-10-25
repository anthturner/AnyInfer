# Meter Spend Across Tenants

A metered document summarizer in native C# that serves several tenants from one batch. It gives the
SDK the prices and context windows the application has verified, sets a spend ceiling the SDK
enforces before each request is sent, keeps a fresh caller-owned ledger for the run and adds it to
an accounting file across runs, paces a hosted gateway client-side, sends inputs that cannot fit
the small model to a larger one, and keeps self-hosted work whose cost cannot be known out of the
"free" column.

None of these decisions are made by the application at request time: the program states policy as
client and request inputs, and reads the results.

## Before You Start

- The .NET 8 SDK and a reference to the local C# prerelease, as described in
  [Install the C# SDK](../guides/csharp-installation.md), and the first call from the
  [C# quickstart](../guides/csharp-quickstart.md). The C# SDK is a locally packaged
  `0.1.0-proof` prerelease, not a NuGet package.
- Nothing else to run it offline. Against real servers, an OpenAI-compatible gateway serving the
  two priced models and, optionally, a self-hosted OpenAI-compatible server.

## The Program

```csharp
--8<-- "examples/csharp-sdk/CookbookPoliciesExample.cs"
```

## How It Works

- **Prices and windows are explicit facts.** `Facts` supplies `ModelCapabilities` per provider
  instance and model at `Override` provenance, which the SDK trusts for cost and for the context
  gate. Each served request's `Usage.CostUsd` is its reported tokens times those rates. Nothing is
  supplied for `lab`, so its cost is unknown, not zero.
- **A preflight is free.** `Budget` estimates input tokens for one explicit target, reserves the
  request's `maxOutputTokens`, and reports whether the request fits and a cost range when prices
  are known. It builds no adapter and sends nothing. For the self-hosted target both answers are
  unknown.
- **The spend policy refuses before dispatch.** Before each attempt, the client estimates the
  attempt's highest cost from trusted prices. `maxRequestUsd` caps one request; `maxTotalUsd` caps
  completed spend plus in-flight reservations plus that estimate. A refused request raises
  `SpendLimitException` with the ceiling, the spend so far, and the estimate, and nothing is sent.
  With `onUnknown` set to `allow` (the default), a target without a trusted price is sent; with
  `refuse`, it is refused.
- **Overflow goes to a bigger window, not to an error.** `Metered` routes to `gateway:small` with
  `gateway:large` as its context-window target. The context gate, on by default, refuses an
  attempt before dispatch when even the conservative floor of the input estimate exceeds a trusted
  window, and the route continues with the context-window targets. `Budget.Fits` is the stricter
  planning answer: it also counts the response reserve and safety headroom, so a request can be
  reported as not fitting and still be sent.
- **The ledger and the store belong to the application.** The client records each completed
  request into the `SpendLedger` it was given, with totals by target and by the `tenant` metadata
  label. Requests whose cost is unknown are counted in `UnknownRequests`, and `Complete` turns
  false. `SpendStore.Accumulate` adds the run's totals to a named bucket in the caller's file. Each
  write replaces the file atomically, but accumulation is not a coordinated read-modify-write
  across threads or processes.
- **Pacing happens inside the client.** `RateLimits` on the gateway's `ProviderSettings` make the
  SDK hold dispatches at least 0.25 seconds apart with at most two in flight. The time a request
  waited appears as the `queued_ms` entry of `Generation.Timing.Phases`.
- **A cache policy is planning input.** A `CachePolicy` in `CacheMode.Auto` asks the SDK to use
  the strongest cache mechanism the target declares. The generic OpenAI-compatible descriptor declares
  none, so no mechanism engages and `Generation.CacheMechanism` stays `null`.

## Offline Run

The example runner answers the gateway and the self-hosted server with scripted responses that
report token usage, and asserts the money. The cases are in
`examples/csharp-sdk/Cases/CookbookPoliciesCases.cs`; from `src/csharp`, run:

```bash
dotnet run --project ../../examples/csharp-sdk/AnyInfer.Examples.csproj --configuration Release
```

The `cookbook.policies.*` cases check that, with a $0.05 run budget:

- a short job is served by `gateway:small` and costs $0.00039 (1,200 input tokens at $0.20 per
  million and 250 output tokens at $0.60 per million);
- an 85 KB document is gated off the 8,192-token small model, served by `gateway:large` for
  $0.02612, and waited more than 150 ms for the gateway's pacing;
- the self-hosted job reports unknown fit, unknown estimate, and unknown cost, and is counted as
  one unknown-cost request rather than as free;
- a second long document is refused before dispatch because $0.02651 already spent plus its
  estimate would pass $0.05, so the gateway receives exactly two requests;
- the ledger's totals by target and by tenant, the persisted `2026-10` bucket, and the printed
  report all agree;
- a later run adds its spend to the same bucket in the version 1 store file, and a document whose
  estimate on the large model is above the $0.04 per-request ceiling is refused before dispatch;
- with `refuseUnknownCost`, the self-hosted job is refused before dispatch with no estimate, and
  the server receives nothing.

## Before Production

- Take prices and context windows from a source you maintain and review; an override is trusted
  exactly as written.
- Size `maxRequestUsd` and the run budget for the most expensive request you intend to allow,
  including the response reserve set by `maxOutputTokens`.
- Keep one writer per accounting file, or coordinate writers yourself; the store is not a
  multi-process ledger.
- Decide whether unknown cost is acceptable for each deployment, and set `onUnknown` accordingly.
- Set `RateLimits` from the provider's published limits; with `respectHeaders` the limiter can also
  wait on provider allowance headers where the descriptor declares them.

Costs here are the SDK's calculation from reported usage and the prices you supply, for the
winning call of each request. They are not a provider invoice, and they do not include tokens spent
on failed attempts.

## See Also

<div class="anyinfer-see-also" markdown>

- [Cost and spending](../concepts/cost.md), [token estimation and budgets](../concepts/budgeting.md),
  and [prompt caching](../concepts/caching.md).
- [Routing](../concepts/routing.md) for context-window fallback and client-side rate limits.
- [C# SDK guide](../guides/csharp-sdk.md#calculate-explicit-accounting-facts) for the standalone
  accounting helpers.
- API: [`SpendPolicy`](/csharp/api/anyinfer.spendpolicy/),
  [`SpendLimitException`](/csharp/api/anyinfer.spendlimitexception/),
  [`SpendLedger`](/csharp/api/anyinfer.capabilities.spendledger/),
  [`SpendStore`](/csharp/api/anyinfer.capabilities.spendstore/),
  [`SpendTotals`](/csharp/api/anyinfer.capabilities.spendtotals/),
  [`ModelCapabilities`](/csharp/api/anyinfer.capabilities.modelcapabilities/),
  [`ContextBudget`](/csharp/api/anyinfer.capabilities.contextbudget/),
  [`RateLimits`](/csharp/api/anyinfer.ratelimits/),
  [`CachePolicy`](/csharp/api/anyinfer.cachepolicy/),
  [`Route`](/csharp/api/anyinfer.route/).

</div>
