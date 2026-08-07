"""The embeddable OpenAI-compatible sidecar frontend.

A wire codec plus an ASGI app around a normal
`AsyncClient` — never a second core. Importing the
codec is free; the ASGI app requires the ``[serve]`` extra.
"""

from .app import create_app
from .openai_codec import (
    chunk_from_event,
    completion_from_generation,
    decode_messages,
    encode_messages,
    final_chunk,
    request_from_openai,
    request_to_openai,
)

__all__ = [
    "chunk_from_event",
    "completion_from_generation",
    "create_app",
    "decode_messages",
    "encode_messages",
    "final_chunk",
    "request_from_openai",
    "request_to_openai",
]
