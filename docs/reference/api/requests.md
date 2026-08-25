# Requests and Messages

The request side of the one primitive: everything a `GenerationRequest` can carry. See
[the event stream](../../concepts/events.md) for how a request becomes output.

<div class="anyinfer-api-block" markdown>

::: anyinfer.GenerationRequest

::: anyinfer.Message

::: anyinfer.Role

::: anyinfer.ContentPart

::: anyinfer.Text

::: anyinfer.ImagePart

::: anyinfer.DocumentPart

::: anyinfer.AudioPart

::: anyinfer.VideoPart

::: anyinfer.system

::: anyinfer.user

::: anyinfer.assistant

::: anyinfer.Sampling

::: anyinfer.ReasoningEffort

::: anyinfer.SchemaSpec

::: anyinfer.SupportsJSONSchema

::: anyinfer.Repair

::: anyinfer.ArenaPolicy

::: anyinfer.ContextRequest

::: anyinfer.ToolSpec

::: anyinfer.ToolChoice

::: anyinfer.ToolResult

::: anyinfer.Target

</div>

## Prompt Caching

Opt-in placement of a provider's prompt cache. Off unless asked for: caching changes what a
provider bills and how long it keeps a copy of the prompt. What it caches is the prefix the
caller sends, on the provider's side; it never skips a call or reuses an answer.

<div class="anyinfer-api-block" markdown>

::: anyinfer.CachePolicy

::: anyinfer.CacheMode

::: anyinfer.CacheMechanism

</div>
