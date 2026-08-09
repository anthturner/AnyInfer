# <provider-id> — Protocol Contract

<!--
Copy to contracts/<provider-id>.md and fill every section, then delete this comment.

A snapshot records exactly what upstream protocol details the adapter depends on — a
dependency list, not a mirror of the provider's reference. It is the input to the drift
check (DRIFT-CHECK.md), which compares it against the provider's current documentation.

Two rules are not negotiable:

  1. Dates are real. Never write a "Last verified" you did not actually verify, and say
     plainly how it was verified — live calls, cassettes, published docs, or code survey.
  2. Update this file in the same change as any adapter wire-behaviour change.

The headings below are what scripts/validate_contracts.py checks. Keep all of them.
-->

Status: <milestone> adapter — **<implemented | planned>**.
Last verified: <YYYY-MM-DD> — <how: live calls, cassettes, published documentation, or code
survey. If it has never been checked against live documentation, say so here.>

## Upstream sources
- <url to the API reference for generation>
- <url to the model-listing reference>
- <url to versioning / changelog / release notes>

## Wire contract
### Endpoints
- `POST <url>` — generation
- `GET <url>` — discovery
- <what stands in for a readiness probe, if anything>
### Auth
- <header name and value shape, and any additional required headers>
- <the environment variable this credential conventionally comes from>
### Version pins
- <version header, query parameter, or path segment sent, and what omitting it does>
### Request fields
- <every field the adapter puts on the wire, and the normalized concept each carries —
  including the shape of system prompts, tool declarations, and structured-output
  directives>
### Response fields
- <every field the adapter reads, including usage accounting and finish reasons, and what
  each maps to in the normalized result>
### Streaming
- <transport (SSE, NDJSON, chunked JSON), event shapes, termination, and where usage
  arrives relative to the finish signal>
- <TTFT rule: which event stops the first-token clock>
### Errors
- <status codes, error body shape, and the headers read to classify a failure — including
  rate-limit and retry headers honored>

## Watchlist
- <what is most likely to drift: version headers, beta flags, undocumented behaviour the
  adapter relies on, fields marked VERIFY above>
