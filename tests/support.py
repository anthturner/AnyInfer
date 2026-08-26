"""Test helpers shared across modules."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from pathlib import Path

import anyinfer as ai
from anyinfer.testing.fakes import FakeOpenAIServer


def make_client(server: FakeOpenAIServer, **client_kwargs: object) -> ai.AsyncClient:
    """Build an async client wired to a fake server."""
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        **client_kwargs,  # type: ignore[arg-type]
    )


def make_sync_client(server: FakeOpenAIServer, **client_kwargs: object) -> ai.Client:
    """Build a sync client wired to a fake server."""
    return ai.Client(
        [
            ai.ProviderSettings.of(
                "openai-compat",
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
        ],
        **client_kwargs,  # type: ignore[arg-type]
    )


def make_multi_client(
    servers: Sequence[tuple[str, FakeOpenAIServer]],
    **client_kwargs: object,
) -> ai.AsyncClient:
    """Build a client with several providers, each backed by its own fake server.

    Used for fallback tests: the providers are distinct registrations of the same dialect,
    which is exactly how a fallback chain across two OpenAI-compatible endpoints behaves.
    """
    return ai.AsyncClient(
        [
            ai.ProviderSettings.of(
                provider_id,
                base_url="https://fake.invalid/v1",
                transport=server.transport(),
            )
            for provider_id, server in servers
        ],
        **client_kwargs,  # type: ignore[arg-type]
    )


def self_signed_cert(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Write a throwaway certificate, its key, and the combined PEM.

    Generated rather than committed: a fixture certificate expires, and a test that starts
    failing on a date is worse than one that costs a few milliseconds.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "anyinfer-test")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    combined_path = tmp_path / "combined.pem"
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_path.write_bytes(cert_bytes)
    key_path.write_bytes(key_bytes)
    combined_path.write_bytes(cert_bytes + key_bytes)
    return cert_path, key_path, combined_path
