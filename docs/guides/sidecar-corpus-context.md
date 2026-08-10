# Reduce an explicit corpus through the sidecar

`anyinfer_context` is stateless: every request carries the caller-approved documents, the
sidecar retains none of them, and only the core client decides what fits. The extension has
a 1,000-document and 5 MiB default envelope ceiling, refuses the inference-spending
`distill` strategy, and requires either a trusted target context window or an explicit
`max_tokens` budget.

```json
{
  "model": "openai:gpt-5-mini",
  "messages": [{"role": "user", "content": "Where is token refresh handled?"}],
  "anyinfer_context": {
    "documents": [
      {"path": "src/auth.py", "content": "...", "pinned": true},
      {"path": "src/session.py", "content": "..."}
    ],
    "query": "token refresh",
    "strategy": "ranked",
    "max_tokens": 6000,
    "placement": "system"
  }
}
```

The non-streaming response includes a content-free summary:

```json
{
  "anyinfer_context": {
    "strategy": "ranked",
    "representation": "ranked",
    "candidate_count": 2,
    "selected_count": 1,
    "omitted_count": 1,
    "estimated_tokens": 4200,
    "complete": false
  }
}
```

That summary answers what was dropped without echoing document paths or content. Streaming
returns the same summary in its terminal extension frame.

Uploading material that the server then omits can waste bandwidth. For large local corpora,
run `anyinfer context` or `anyinfer run --context-dir` beside the files. A non-Python client
can also call the library's `context.plan()` in a small helper before upload.

When exposing the sidecar beyond loopback, source documents routinely cross the network.
AnyInfer therefore requires both `--allow-remote-exposure` and a bearer token for a
non-loopback bind; use TLS at the reverse proxy as well.
