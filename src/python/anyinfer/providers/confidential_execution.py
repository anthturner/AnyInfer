"""Gate local generation on detected confidential-execution readiness.

Composes over an already-configured local adapter (`llama_cpp`, `lm_studio`, `ollama`)
rather than subclassing any of them. Generation raises a typed error when the detected
local conditions do not meet the requested policy; discovery and health remain available.

Enforcement and any pre-flight capability check a caller makes both call
`anyinfer.local.attestation.confidential_execution_status` — one source of truth, so they
can never drift out of sync with each other.

**What the gate is, today.** The `end_to_end` field this adapter refuses on is TEE
*detection*, not verified attestation: no quote is generated or checked against a vendor
root of trust. The refusal path is real and the fail-closed posture holds, but a host that
passes this gate has not proven anything to a remote party — a fabricated device node
satisfies every probe. A successful `generate()` here is not cryptographic assurance to
a remote party. Hardware quote verification is not implemented.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING

from ..errors import ConfidentialExecutionError
from ..local.attestation import confidential_execution_status
from ..types.capabilities import DiscoveredModel, Health
from .base import AdapterEvent, ProviderAdapter, WireRequest, aclosing_if_supported

if TYPE_CHECKING:
    from ..local.backends import Backend
    from ..local.store import ResolvedModel

__all__ = ["ConfidentialExecutionAdapter"]


class ConfidentialExecutionAdapter:
    """Wrap a local adapter, refusing generation unless local readiness is detected.

    Discovery and health pass straight through to the inner adapter unchanged —
    The gate checks detected execution conditions, not model availability or process
    reachability. Passing it does not verify a hardware attestation quote.
    """

    def __init__(
        self,
        inner: ProviderAdapter,
        *,
        backend: Backend,
        model: ResolvedModel | None = None,
    ) -> None:
        """Bind the wrapper to one inner adapter and the backend/model it will check.

        Args:
            inner: An already-configured local adapter instance to delegate to once
                the local readiness check passes.
            backend: The local backend `inner` runs — passed straight to
                `confidential_execution_status` on every `generate()` call.
            model: The selected model, when known; also passed straight through. See
                `confidential_execution_status`'s own docstring for what a missing model
                means for the check.
        """
        self._inner = inner
        self._backend = backend
        self._model = model

    async def list_models(self) -> Sequence[DiscoveredModel]:
        """Delegate to the inner adapter unchanged."""
        return await self._inner.list_models()

    async def health(self) -> Health:
        """Delegate to the inner adapter unchanged."""
        return await self._inner.health()

    async def aclose(self) -> None:
        """Delegate to the inner adapter unchanged."""
        await self._inner.aclose()

    async def generate(self, req: WireRequest) -> AsyncIterator[AdapterEvent]:
        """Check local readiness, then generate; refuse before dispatch if it fails.

        Raises:
            anyinfer.errors.ConfidentialExecutionError: The local readiness conditions
                are not detected on this host. Carries
                `ConfidentialExecutionStatus.detail` so a caller can render *why*.
        """
        status = confidential_execution_status(backend=self._backend, model=self._model)
        if not status.end_to_end:
            raise ConfidentialExecutionError(
                f"confidential execution was requested but is not available: {status.detail}"
            )
        # An early close of this generator must also close the inner adapter's, or its
        # open connection is left to finalize during GC instead of closing
        # deterministically — `aclosing_if_supported` rather than `contextlib.aclosing`
        # because `self._inner` is `ProviderAdapter`-typed, and `GeneratesText.generate()`
        # does not promise `.aclose()` (see that Protocol's docstring).
        async with aclosing_if_supported(self._inner.generate(req)) as events:
            async for event in events:
                yield event
