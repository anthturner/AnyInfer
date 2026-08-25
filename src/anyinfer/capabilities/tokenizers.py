"""Exact token counting for the models whose tokenizer is publishable.

The core ships a byte heuristic and no tokenizer, deliberately: a mandatory tokenizer
dependency for every install is the wrong trade when most callers never budget context.
This module is the opt-in other half, behind the ``tokenizers`` extra.

**What "exact" buys, precisely.** An estimate is two numbers with opposite biases: the
planning figure `TokenEstimate.tokens` should err high, and the floor should err low
because the pre-dispatch gate *refuses* on it. The byte heuristic's floor divides by 8, so
it under-counts by roughly half and the gate lets through requests that will overflow. An
exact count sets ``floor == tokens``, which is what lets the gate refuse before a round
trip instead of after one.

That exactness is scoped to the *text*. Chat framing — role markers, separators — is
dialect-specific and is added by `estimate_request` to the planning figure only, never to
the floor. So an exact text count remains a true lower bound on what a provider charges,
which is the property the gate needs.

**Only local tokenizers live here.** A provider's own count-tokens endpoint and
llama-server's ``/tokenize`` would both be more exact still, and neither fits: the
`TokenEstimator` protocol is synchronous, and a synchronous HTTP call inside an async
client stalls the event loop for every concurrent request. Making them work means an async
estimator protocol, which is a deliberate future change rather than something to smuggle
in behind a blocking call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..errors import ConfigError
from .estimate import TokenEstimate

if TYPE_CHECKING:  # pragma: no cover — annotation only
    from .estimate import TokenEstimator

__all__ = [
    "DEFAULT_ENCODING",
    "TargetAwareTokenEstimator",
    "TiktokenEstimator",
    "estimator_for",
]

DEFAULT_ENCODING = "o200k_base"
"""Encoding used for a model tiktoken does not recognize.

The current OpenAI-family encoding rather than the older ``cl100k_base``: an unrecognized
model id is far more likely to be a model newer than the installed tiktoken than one older
than it, and the newer encoding packs text more tightly — so guessing it under-counts,
which keeps the floor a floor.
"""


@runtime_checkable
class TargetAwareTokenEstimator(Protocol):
    """An estimator that can specialize itself for one resolved target.

    An optional extension to `TokenEstimator`, not a replacement:
    the tokenizer a count needs depends on the model, and `TokenEstimator.estimate` sees
    only text. An estimator implementing this is asked for a specialized instance once per
    target; one that does not is used as-is, which is why the shipped heuristic needs no
    change.
    """

    def for_model(self, provider_id: str, model: str) -> TokenEstimator:
        """Return the estimator to use for one provider and model."""
        ...


def estimator_for(estimator: TokenEstimator, provider_id: str, model: str) -> TokenEstimator:
    """Specialize an estimator for one target, when it knows how to be specialized.

    Args:
        estimator: The client's configured estimator.
        provider_id: The resolved provider.
        model: The resolved model id.

    Returns:
        A target-specific estimator, or ``estimator`` unchanged when it is not
        target-aware.
    """
    if isinstance(estimator, TargetAwareTokenEstimator):
        return estimator.for_model(provider_id, model)
    return estimator


class TiktokenEstimator:
    """Exact token counts via ``tiktoken``, for models whose encoding it publishes.

    Exact for OpenAI's own models and for the many open-weight families that adopted the
    same encodings. **Not** exact for Anthropic, Gemini, or Cohere, whose tokenizers are
    not published — those fall back to `DEFAULT_ENCODING`, which is a better guess than
    counting bytes but is still a guess, and is reported as one.

    Instances are cheap and cache their encodings process-wide, so `for_model` may be
    called per request.

    Args:
        encoding: Pin one encoding for every model instead of selecting per model. Use
            when serving a known open-weight family through an OpenAI-compatible endpoint,
            where the model id tells tiktoken nothing.

    Raises:
        anyinfer.errors.ConfigError: If ``tiktoken`` is not installed.
    """

    __slots__ = ("_encoder", "_exact", "_pinned")

    _ENCODINGS: dict[str, Any] = {}
    """Process-wide encoding cache. Loading one reads a vocabulary file; doing it per
    request would dominate the cost of the count it enables."""

    def __init__(self, encoding: str | None = None) -> None:
        self._pinned = encoding
        self._encoder = self._encoding_named(encoding or DEFAULT_ENCODING)
        # A pinned encoding is the caller's assertion about their own deployment, so it is
        # trusted as exact. An unpinned default instance has not been told which model it
        # is counting for, so it is not.
        self._exact = encoding is not None

    @classmethod
    def _module(cls) -> Any:
        """Import ``tiktoken``, naming the extra when it is absent.

        Raises:
            anyinfer.errors.ConfigError: If the optional dependency is not installed.
        """
        try:
            import tiktoken
        except ImportError as exc:  # pragma: no cover — exercised by the absence test
            raise ConfigError(
                "exact token counting needs the optional 'tiktoken' dependency",
                hint="install anyinfer[tokenizers], or keep the default byte heuristic",
            ) from exc
        return tiktoken

    @classmethod
    def _encoding_named(cls, name: str) -> Any:
        """Load one encoding by name, caching it process-wide."""
        cached = cls._ENCODINGS.get(name)
        if cached is None:
            cached = cls._module().get_encoding(name)
            cls._ENCODINGS[name] = cached
        return cached

    def for_model(self, provider_id: str, model: str) -> TiktokenEstimator:
        """Return an estimator using the encoding this model actually uses.

        Args:
            provider_id: The resolved provider; unused today and accepted because the
                mapping from model id to encoding is a *provider's* fact, and a future
                provider-specific table belongs here rather than at the call site.
            model: The resolved model id.

        Returns:
            ``self`` when the instance pins an encoding; otherwise an instance holding the
            encoding tiktoken names for this model, or the default when it names none.
        """
        del provider_id
        if self._pinned is not None:
            return self
        specialized = TiktokenEstimator.__new__(TiktokenEstimator)
        specialized._pinned = None
        try:
            encoder = self._module().encoding_for_model(model)
            exact = True
        except (KeyError, ValueError):
            # tiktoken raises KeyError for a model it does not know. Not a failure: it is
            # the honest answer that this model's tokenizer is not published, and the
            # right response is a good guess reported as a guess.
            encoder = self._encoder
            exact = False
        specialized._encoder = encoder
        specialized._exact = exact
        return specialized

    def estimate(self, text: str) -> TokenEstimate:
        """Count ``text`` with this instance's encoding.

        Returns:
            ``TokenEstimate(n, n)`` when the encoding is known to be this model's, so the
            pre-dispatch gate can act on the floor with full force. Otherwise the count is
            the planning figure and the floor is held slightly below it, because a
            substituted encoding can over-count and a floor that over-claims would refuse
            requests that fit.
        """
        if not text:
            return TokenEstimate(0, 0)
        count = len(self._encoder.encode(text, disallowed_special=()))
        if self._exact:
            return TokenEstimate(count, count)
        return TokenEstimate(count, int(count * _SUBSTITUTED_FLOOR_RATIO))


_SUBSTITUTED_FLOOR_RATIO = 0.75
"""How much of a substituted encoding's count may be claimed as a floor.

Cross-tokenizer counts of the same text on current vocabularies differ by well under 25%
for ordinary prose and code, so three quarters is a lower bound that holds while still
being far tighter than the byte heuristic's — which is the entire point of installing a
tokenizer. Not a tuning knob: a wrong value here silently changes which requests the
pre-dispatch gate refuses.
"""
