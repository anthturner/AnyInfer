# Results and stream events

The output side: the final `Generation`, its usage and timing, and the typed events a
stream yields on the way there. Ordering guarantees are documented in
[the event stream](../../concepts/events.md).

## The final result

<div class="anyinfer-api-block" markdown>

::: anyinfer.Generation

::: anyinfer.Usage

::: anyinfer.Timing

::: anyinfer.AttemptRecord

::: anyinfer.Outcome

::: anyinfer.ErrorInfo

::: anyinfer.FinishReason

</div>

## Stream events

<div class="anyinfer-api-block" markdown>

::: anyinfer.StreamEvent

::: anyinfer.TextDelta

::: anyinfer.ReasoningDelta

::: anyinfer.ToolCall

::: anyinfer.ToolCallDelta

::: anyinfer.UsageUpdate

::: anyinfer.TimingMark

::: anyinfer.TimingMarkName

::: anyinfer.AttemptFailed

::: anyinfer.StreamEnded

</div>
