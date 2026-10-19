# Modern OpenAI streaming Accept header parity

Resume from the first unchecked box. This is a bounded source follow-up under POL.5 of
ANYINFER_CSHARP_SDK_POLICIES.md. Owner cab; root owns shared gates and Git.

## Settled behavior

The Python public OpenAI-compatible streaming path explicitly supplies
accept: text/event-stream (src/python/anyinfer/providers/openai_compat.py near308-311).
Native Providers/OpenAIChatAdapter.cs CreateRequest currently never supplies Accept.
This is semantic request metadata, distinct from transport-generated Host/User-Agent/
Accept-Encoding/Connection/Content-Length and nonstream default Accept.

For modern/public generation with Stream true, send the same explicit Accept header
through the existing request construction path. Follow Python precedence over configured
client header defaults after reading the primary source. Buffered modern generation and
the direct legacy/Frozen wire profile retain their current behavior. Response parsing,
buffered degradation, cancellation, governor lifetime, retry/routing and schema handling
are unchanged. Update the consumed behavior in contracts/openai-compat.md in the same
change; do not alter verification dates or imply new upstream research.

## Ownership and checks

- Own src/csharp/AnyInfer/Providers/OpenAIChatAdapter.cs only its request-header path,
  new src/csharp/AnyInfer.Tests/ModernStreamHeaderTests.cs,
  contracts/openai-compat.md and this leaf. Preserve all other authors' edits.
- Tests use public client + real offline HttpMessageHandler to inspect actual requests;
  cover modern streaming, buffered modern and configured-header precedence. A narrow
  existing direct legacy WireRequest seam may verify Frozen isolation, without changing
  its production behavior. Do not edit observers, checker, corpus or shared config.
- Root alone builds/runs tests and comparison. No author process/Git action.

- [x] **S.1** Add the public modern streaming semantic Accept header and contract text,
  preserving buffered/legacy paths. Gate: source trace to Python and SAVED/HELD.
- [x] **S.2** Add actual public-handler request controls, including configured-header
  precedence and buffered/legacy isolation. Re-read/tick owned boxes and NOTE deviations.
  Gate: static source/test trace and SAVED/HELD, with no author native process.
- [x] **S.3** Root cold-reviews, compiles/runs focused tests, then batches native unit/
  conformance and preservation gates with the coherent source follow-up. A fresh stamped
  policy run must retain and compare the semantic header rather than waive it.

> NOTE: S.1/S.2 source trace was rechecked against Python's per-request streaming header on
> 2026-10-19: configured headers are applied first, then modern `stream: true` replaces any
> configured Accept with `Accept: text/event-stream`. Buffered modern generation and direct
> frozen WireRequests preserve configured Accept behavior. Offline handler controls cover all
> three paths. Root retains all gates; no author process ran.

> NOTE: Root accepts S.3's bounded source gate: cold review is clean, three header tests
> pass in the coherent 22-test focused batch, then 679 native unit/93 conformance tests,
> accounting 42 shared plus two observed native boundaries, and FrozenV0 102/102 pass with
> no compiler warnings/errors or changed released assets. After the observer's header
> redaction correction, root compares all 34 actual header pairs, including six semantic
> streaming Accept pairs, under the held strict rules. The fresh stamped profile advances
> to 26/29; its remaining repair-message and early-stream capture differences are separate.
