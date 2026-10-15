"""Recording real provider traffic into cassettes, and refusing to ship a leaky one.

Cassettes are how this project verifies adapters against what providers *actually send*
rather than what we believe they send. Recording one requires an account, and no
maintainer will ever hold accounts on every supported provider — so the recording path
is built for contribution: someone who already has a Groq key runs the conformance suite
against it and gets committable cassettes out the other end.

That framing is exactly why this module exists rather than leaving `CassetteTransport` to
be driven by hand. A contributed cassette is a file that a stranger's live API traffic
went into, opened by a maintainer who cannot know what was in it. `Cassette.save()`
already redacts registered secrets and strikes auth headers wholesale, but redaction only
removes what it was told about: an API key the caller never routed through
`anyinfer.credentials`, a session token a provider chose to echo into a response body, or
an account id in an error message are all invisible to it.

So `audit_cassette` reads the *saved* bytes back and looks for credential-shaped survivors
independently of what redaction knew. It is deliberately a separate pass with its own
notion of "secret-shaped", because a check that shares its inputs with the thing it is
checking cannot catch that thing's blind spots. It is heuristic, so it reports findings
for a human rather than silently editing — but it is applied before a cassette is offered
for commit, and a finding blocks the write.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .cassettes import Cassette, Interaction

__all__ = [
    "SECRET_SHAPES",
    "AuditFinding",
    "audit_cassette",
    "audit_interaction",
]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """One credential-shaped string that survived redaction.

    Attributes:
        interaction: Index of the interaction it appeared in.
        where: Which part carried it — ``url``, ``request_body``, ``body``, or a header
            name.
        shape: Name of the pattern that matched, e.g. ``"bearer-token"``.
        excerpt: A short, masked excerpt for the report. Never the full value: a finding
            printed to a terminal or a CI log must not itself become the leak.
    """

    interaction: int
    where: str
    shape: str
    excerpt: str

    def __str__(self) -> str:
        """One line for a terminal report."""
        return f"interaction {self.interaction} {self.where}: {self.shape} ({self.excerpt})"


SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Vendor-prefixed keys. The prefixes are public conventions, which is what makes
    # them findable: OpenAI's sk-, Anthropic's sk-ant-, Google's AIza, xAI's xai-.
    ("vendor-api-key", re.compile(r"\b(?:sk-ant-|sk-|xai-|gsk_|AIza|co-|r8_)[A-Za-z0-9_\-]{16,}")),
    # A bearer token that was written into a body rather than a header, so the
    # header-stripping in Cassette.save() never saw it.
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}")),
    # JWTs: three base64url segments. Providers echo these in error bodies.
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    # AWS access key ids have a fixed, unmistakable shape.
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # Private key material, which should never be within a mile of a cassette.
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    # Long opaque hex/base64 runs assigned to a credential-ish key name. Narrower than
    # "any long string" on purpose: response bodies are full of base64 embeddings and
    # request ids, and a check that cries wolf gets turned off.
    (
        "credential-field",
        re.compile(
            r'"(?:[a-z_]*(?:api[_-]?key|secret|token|password|credential)[a-z_]*)"\s*:\s*'
            r'"(?!\[redacted\])[^"]{12,}"',
            re.IGNORECASE,
        ),
    ),
)
"""Credential shapes an audit looks for, independently of what redaction knew about.

Each is a *public* convention — a documented key prefix, a standard token encoding — which
is precisely why it can be matched without knowing the secret. Anything genuinely opaque
and unprefixed cannot be found this way, which is why `audit_cassette` reports findings
for a human rather than claiming a cassette is clean."""

_PLACEHOLDER = re.compile(r"^\[redacted\]$|^cassette-replay-key$", re.IGNORECASE)


def _mask(value: str) -> str:
    """A short excerpt that identifies a finding without reprinting the secret."""
    collapsed = " ".join(value.split())
    if len(collapsed) <= 12:
        return f"{collapsed[:4]}…"
    return f"{collapsed[:6]}…{collapsed[-2:]} ({len(collapsed)} chars)"


def audit_interaction(interaction: Interaction, index: int = 0) -> list[AuditFinding]:
    """Findings for one recorded interaction.

    Args:
        interaction: The interaction as it would be written to disk.
        index: Its position in the cassette, for the report.

    Returns:
        Every credential-shaped survivor, in scan order. An empty list means nothing
        matched — not that the interaction is provably clean.
    """
    findings: list[AuditFinding] = []
    fields: list[tuple[str, str]] = [
        ("url", interaction.url),
        ("request_body", interaction.request_body or ""),
        ("body", interaction.body or ""),
    ]
    fields.extend((f"header:{name}", value) for name, value in interaction.headers.items())

    for where, text in fields:
        if not text or _PLACEHOLDER.match(text.strip()):
            continue
        for shape, pattern in SECRET_SHAPES:
            for match in pattern.finditer(text):
                findings.append(AuditFinding(index, where, shape, _mask(match.group(0))))
    return findings


def audit_cassette(source: Cassette | Path | Iterable[Interaction]) -> list[AuditFinding]:
    """Findings across a whole cassette.

    A `Path` is read from disk, which is the form that matters: it audits the bytes that
    would actually be committed, after `Cassette.save()` has applied redaction, rather
    than the in-memory objects redaction was handed.

    Args:
        source: A cassette, a path to a saved cassette file, or interactions directly.

    Returns:
        Every finding, in cassette order.
    """
    if isinstance(source, Path):
        data = json.loads(source.read_text(encoding="utf-8"))
        interactions: Sequence[Interaction] = [
            Interaction.from_json(i) for i in data.get("interactions", [])
        ]
    elif isinstance(source, Cassette):
        interactions = source.interactions
    else:
        interactions = list(source)

    findings: list[AuditFinding] = []
    for index, interaction in enumerate(interactions):
        findings.extend(audit_interaction(interaction, index))
    return findings
