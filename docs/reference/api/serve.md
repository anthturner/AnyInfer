# Serve

The `anyinfer.serve` frontend: an OpenAI-compatible loopback service over any configured
provider, embeddable as an ASGI app. Guide: [serve](../../serve/README.md).

## Application

<div class="anyinfer-api-block" markdown>

::: anyinfer.serve.create_app

</div>

## OpenAI codec

The translation layer between the OpenAI wire dialect and AnyInfer's native types
(see the [architecture overview](../../contributing/architecture.md)). Useful directly
when embedding the frontend or building a custom edge.

<div class="anyinfer-api-block" markdown>

::: anyinfer.serve.request_from_openai

::: anyinfer.serve.request_to_openai

::: anyinfer.serve.completion_from_generation

::: anyinfer.serve.chunk_from_event

::: anyinfer.serve.final_chunk

::: anyinfer.serve.encode_messages

::: anyinfer.serve.decode_messages

</div>
