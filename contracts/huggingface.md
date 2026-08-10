# huggingface — Protocol Contract

Status: **implemented** — `local/sources/huggingface.py`, `scripts/pin_catalog.py`.
Last verified: 2026-08-10 — live responses from `huggingface.co/api/models/...` observed
while re-pinning the Qwen2.5-VL weights and projector companion. The full 42-repository
catalog was last refreshed 2026-08-08.

**Not an inference provider.** Hugging Face is a *weights source*: AnyInfer reads repository
listings to resolve, size, and verify model files, and never sends it a generation request.
It is in this directory because it is a third-party HTTP protocol the library depends on, and
the drift check exists to catch it moving — the same discipline every inference provider gets.

## Why we speak this directly

The slim-core rule keeps mandatory dependencies to `httpx2` + `jsonschema`, so
`huggingface_hub` is not available. The scope of what is re-implemented is deliberately
bounded and should stay that way: **two JSON endpoints, one download URL shape, no
cache-layout emulation, no upload, no inference API.** If that scope grows, the decision to
skip the official client deserves re-litigating explicitly rather than by accretion.

## Upstream sources
- https://huggingface.co/docs/hub/api
- https://huggingface.co/docs/hub/security-tokens
- https://huggingface.co/docs/hub/models-gated

## Wire contract

### Endpoints
- `GET https://huggingface.co/api/models/{repo}/revision/{revision}` — resolve a branch or
  tag to an immutable commit.
- `GET https://huggingface.co/api/models/{repo}/tree/{sha}?recursive=1` — list every file at
  a commit, with sizes and digests. Paginated via the `Link` header (`rel="next"`).
- `GET https://huggingface.co/{repo}/resolve/{sha}/{path}` — the file's bytes. Redirects to a
  CDN on a different host.
- Base URL overridable with `HF_ENDPOINT` for an enterprise deployment.

### Auth
- `Authorization: Bearer <token>`, from `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN`.
- **The header is dropped on any cross-origin redirect.** `resolve` URLs redirect to a CDN;
  forwarding a bearer token to whatever host a redirect names is a credential leak. Redirects
  are therefore followed by hand rather than with `follow_redirects=True`, and the token is
  re-sent only on a same-scheme, same-host, same-port hop.
- Anonymous access works for public repositories; a token is needed for gated and private
  ones.

### Version pins
- None. The API is unversioned; behavior is tracked by this snapshot and the drift check.

### Request fields
- None beyond the path. `recursive=1` on the tree endpoint; `Range: bytes=<n>-` on `resolve`
  for resumed transfers.

### Response fields read
- `revision` endpoint: **`sha`** — a 40-character commit id. A branch name is always resolved
  to a commit before anything is downloaded, so a repository that moves under us is a
  detectable event rather than a silent swap.
- `tree` endpoint, per entry: **`type`** (`"file"` / `"directory"`), **`path`**, **`size`**,
  **`oid`** (a git blob sha1 for small files), and for LFS objects **`lfs.oid`** (a
  **sha256** of the content) and **`lfs.size`**.
- `xetHash` is present on some entries and is deliberately **not** read — Xet is a transfer
  optimization whose hash is not the content's sha256.
- `resolve`: `Content-Length`, `Location` (302), and the body.

### Streaming
- Not applicable. File bodies are ordinary byte streams; resumption uses HTTP `Range`.

### Errors
- `401` / `403` → `LocalRuntimeError` whose hint names the model page and the token
  environment variable, because "authentication failed" is useless advice for a gated
  repository whose terms have not been accepted.
- `404` → `LocalRuntimeError` pointing at catalog staleness (a renamed or deleted repository)
  and the pin script.
- `416` on a resumed range → the partial file is discarded and the transfer restarts.
- Any other `4xx`/`5xx` → `LocalRuntimeError` naming the status.

## Trust model

Digests from this API are **trust-on-first-use**: we trust the API for *what the bytes should
be*, then verify the bytes against it. That is a genuine improvement over trusting the
transfer, and recording the digest in the store index turns a later upstream change into a
detectable event. It is not the same as a pinned hash, and the code and docs say so rather
than implying the result is pinned.

Catalog-shipped entries *are* pinned: `scripts/pin_catalog.py` reads `lfs.oid` at pin time
and writes it into `models.json`, so the shipped path verifies against a hash that a human
reviewed in a pull request.

Vision projectors follow the same rule. A vision candidate names one exact `mmproj` path;
the pin pass requires that path in the same immutable tree, records its size and LFS sha256,
and assigns it the `projector` role. Auxiliary-file name matching is never used to choose a
projector.

File names in a tree response are **attacker-influenced input** and are validated before any
file is opened: absolute paths, `..` segments, drive letters, NUL bytes, and reserved Windows
device names are rejected, and every destination is checked for containment after resolution.

Pickle-format weights (`*.bin`, `*.pt`, `*.pth`, `*.ckpt`) are excluded from snapshots by
default because loading them executes arbitrary code.

## Watchlist

- **Xet-backed transfer.** Hugging Face has been migrating LFS storage to Xet. If `resolve`
  URLs ever stop being plain redirected byte ranges, this resolver breaks. Mitigation: the
  catalog's pinned entries carry direct URLs and sha256 digests, so the pinned path degrades
  to "a URL that 404s" — a detectable, reported failure — rather than to silent corruption.
- **`lfs.oid` semantics.** Everything downstream assumes it is a sha256 of the content. If
  that ever changes, verification would fail loudly rather than silently accept, but the
  contract would need re-writing.
- **Tree pagination.** The `Link` header shape is what drives multi-page listings; large
  repositories are the only place it is exercised.
- **Redirect hosts.** The token-dropping rule is origin-based, so a future same-host CDN
  would keep receiving the token. That is correct today and worth re-checking if the
  download host changes.
- **Rate limits.** Unauthenticated listing is rate-limited; the weekly drift check issues one
  `HEAD` per variant rather than per file for this reason.
- **Gated-repository flow.** The 401/403 hint text assumes terms are accepted on the model
  page with the token's own account. Re-verify if the gating flow changes.
