"""AWS SigV4 signing, Google token acquisition, and the binary event-stream decoder."""

from __future__ import annotations

import binascii
import contextlib
import datetime as dt
import json
import struct

import pytest

from anyinfer.errors import ConfigError, CredentialError, StreamProtocolError
from anyinfer.providers.cloud_auth import (
    AwsCredentials,
    GoogleTokenSource,
    resolve_aws_credentials,
    sigv4_headers,
)
from anyinfer.providers.eventstream import iter_event_stream
from support import self_signed_cert

# ---- SigV4 ---------------------------------------------------------------------------

CREDS = AwsCredentials("AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
SIGNED_AT = dt.datetime(2026, 8, 7, 12, 0, 0, tzinfo=dt.UTC)


def _sign(**overrides: object) -> dict[str, str]:
    kwargs: dict[str, object] = {
        "credentials": CREDS,
        "method": "POST",
        "url": "https://bedrock-runtime.us-east-1.amazonaws.com/model/x/converse",
        "region": "us-east-1",
        "service": "bedrock",
        "body": b'{"messages":[]}',
        "headers": {"content-type": "application/json"},
        "now": SIGNED_AT,
    }
    kwargs.update(overrides)
    return sigv4_headers(**kwargs)  # type: ignore[arg-type]


def test_signature_has_the_documented_shape():
    headers = _sign()
    auth = headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 ")
    assert "Credential=AKIDEXAMPLE/20260807/us-east-1/bedrock/aws4_request" in auth
    assert "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date" in auth
    assert "Signature=" in auth
    assert headers["x-amz-date"] == "20260807T120000Z"


def test_the_payload_hash_covers_the_body():
    import hashlib

    body = b'{"messages":[{"role":"user"}]}'
    headers = _sign(body=body)
    assert headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()


def test_a_different_body_produces_a_different_signature():
    assert _sign(body=b"a")["authorization"] != _sign(body=b"b")["authorization"]


def test_signing_is_deterministic():
    assert _sign() == _sign()


def test_session_tokens_are_signed_and_sent():
    temporary = AwsCredentials(CREDS.access_key_id, CREDS.secret_access_key, "SESSION")
    headers = _sign(credentials=temporary)
    assert headers["x-amz-security-token"] == "SESSION"
    assert "x-amz-security-token" in headers["authorization"], "and it is signed"


def test_model_ids_survive_path_encoding():
    """Inference-profile ids and ARNs carry colons that must not read as separators."""
    arn = "arn%3Aaws%3Abedrock%3Aus-east-1%3A1%3Ainference-profile%2Fx"
    headers = _sign(url=f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{arn}/converse")
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 ")


def test_a_query_string_is_canonicalized():
    with_query = _sign(url="https://host.invalid/path?b=2&a=1")
    reordered = _sign(url="https://host.invalid/path?a=1&b=2")
    assert with_query["authorization"] == reordered["authorization"]


# ---- credential resolution -----------------------------------------------------------


def test_explicit_keys_win(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "from-env")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "env-secret")
    resolved = resolve_aws_credentials(
        {"aws_access_key_id": "explicit", "aws_secret_access_key": "explicit-secret"}
    )
    assert resolved is not None
    assert resolved.access_key_id == "explicit"


def test_a_half_supplied_key_pair_is_actionable():
    with pytest.raises(ConfigError) as excinfo:
        resolve_aws_credentials({"aws_access_key_id": "only-the-id"})
    assert excinfo.value.hint is not None
    assert "aws_secret_access_key" in str(excinfo.value)


def test_the_environment_is_the_last_resort(monkeypatch):
    monkeypatch.setattr(
        "anyinfer.providers.cloud_auth._aws_credentials_from_boto3", lambda options: None
    )
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "env-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "env-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "env-token")

    resolved = resolve_aws_credentials({})
    assert resolved == AwsCredentials("env-key", "env-secret", "env-token")


def test_no_credentials_anywhere_reports_none(monkeypatch):
    monkeypatch.setattr(
        "anyinfer.providers.cloud_auth._aws_credentials_from_boto3", lambda options: None
    )
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    assert resolve_aws_credentials({}) is None


# ---- Google tokens -------------------------------------------------------------------


def test_an_explicit_token_is_used_verbatim():
    """A caller-supplied token is theirs to manage; nothing is fetched or refreshed."""
    source = GoogleTokenSource(explicit_token="ya29.provided")
    assert source.token() == "ya29.provided"
    assert source.token() == "ya29.provided"


def test_a_missing_credential_source_is_actionable(monkeypatch):
    monkeypatch.setattr(GoogleTokenSource, "_from_google_auth", lambda self: None)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    source = GoogleTokenSource(options={})
    with pytest.raises(CredentialError) as excinfo:
        source.token()

    assert excinfo.value.hint is not None
    assert "gcloud auth print-access-token" in excinfo.value.hint


def test_tokens_are_cached_until_they_near_expiry(monkeypatch):
    calls: list[int] = []

    def fake_acquire(self):
        calls.append(1)
        return "token-value", 3600.0

    monkeypatch.setattr(GoogleTokenSource, "_acquire", fake_acquire)
    source = GoogleTokenSource(options={})

    assert source.token() == "token-value"
    assert source.token() == "token-value"
    assert len(calls) == 1, "a live token is not re-acquired"


def test_an_expiring_token_is_refreshed(monkeypatch):
    calls: list[int] = []

    def fake_acquire(self):
        calls.append(1)
        # A lifetime inside the refresh margin, so the next read must re-acquire.
        return f"token-{len(calls)}", 1.0

    monkeypatch.setattr(GoogleTokenSource, "_acquire", fake_acquire)
    source = GoogleTokenSource(options={})

    assert source.token() == "token-1"
    assert source.token() == "token-2", "a near-expiry token is refreshed"


def test_a_credentials_file_that_is_not_a_service_account_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(GoogleTokenSource, "_from_google_auth", lambda self: None)
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")

    source = GoogleTokenSource(options={"credentials_file": str(path)})
    with pytest.raises(CredentialError) as excinfo:
        source.token()

    assert "service-account" in str(excinfo.value)


def test_the_token_exchange_honors_the_instances_connection_settings(monkeypatch, tmp_path):
    """One instance must not make two different trust decisions.

    The data plane has honored `proxy`/`verify`/`client_cert` per instance since they
    shipped, but the token exchange opened a bare client — so a Vertex instance behind an
    intercepting proxy with a corporate CA had `generateContent` succeed and its own
    authentication fail TLS verification, with nothing saying why.
    """
    import ssl

    import httpx2

    seen: dict[str, object] = {}

    class _StopError(Exception):
        pass

    def recording_client(*args, **kwargs):
        # Recorded and stopped rather than constructed: what is under test is which
        # arguments reach httpx, not what httpx then does with them.
        seen.update(kwargs)
        raise _StopError

    monkeypatch.setattr(httpx2, "Client", recording_client)

    cert, key, _ = self_signed_cert(tmp_path)
    source = GoogleTokenSource(
        options={},
        proxy="http://corp-proxy:3128",
        verify=str(cert),
        client_cert=(str(cert), str(key)),
    )
    with contextlib.suppress(_StopError):
        source._exchange("not-a-real-assertion")

    assert seen["proxy"] == "http://corp-proxy:3128"
    # Resolved through the shared `tls_kwargs`, so the token exchange gets one SSL context
    # built exactly the way the data plane builds one — not a CA path and a certificate on
    # two deprecated keywords that httpx refuses to accept together.
    assert isinstance(seen["verify"], ssl.SSLContext)
    assert seen["verify"].verify_mode == ssl.CERT_REQUIRED
    assert "cert" not in seen


def test_an_unreadable_ca_bundle_on_the_token_path_is_a_config_error():
    """The same actionable failure the data plane gives, not a bare `FileNotFoundError`."""
    source = GoogleTokenSource(options={}, verify="/no/such/corp-ca.pem")
    with pytest.raises(ConfigError, match="cannot load the CA bundle"):
        source._exchange("not-a-real-assertion")


def test_a_supplied_transport_takes_over_from_the_connection_settings(monkeypatch):
    """Same rule as the data plane: a transport owns connection handling entirely."""
    import httpx2

    seen: dict[str, object] = {}

    class _StopError(Exception):
        pass

    def recording_client(*args, **kwargs):
        seen.update(kwargs)
        raise _StopError

    monkeypatch.setattr(httpx2, "Client", recording_client)

    source = GoogleTokenSource(
        options={},
        transport=httpx2.MockTransport(lambda request: httpx2.Response(500)),
        proxy="http://corp-proxy:3128",
        verify=False,
    )
    with contextlib.suppress(_StopError):
        source._exchange("not-a-real-assertion")

    assert "proxy" not in seen
    assert "verify" not in seen


def test_vertex_passes_its_connection_settings_to_both_planes():
    """The adapter rebuilds a config for its Gemini parent; the settings must survive it."""
    from anyinfer.providers.base import ProviderConfig
    from anyinfer.providers.vertex import VertexAdapter

    adapter = VertexAdapter(
        ProviderConfig(
            provider_id="vertex",
            options={"project": "p", "location": "global"},
            proxy="http://corp-proxy:3128",
            verify=False,
        )
    )

    assert adapter._tokens._proxy == "http://corp-proxy:3128"
    assert adapter._tokens._verify is False


# ---- the binary event stream ---------------------------------------------------------


def _frame(event_type: str, payload: dict, *, message_type: str = "event") -> bytes:
    """Build one vnd.amazon.eventstream frame the way AWS does."""
    body = json.dumps(payload).encode("utf-8")
    headers = b""
    for name, value in ((":event-type", event_type), (":message-type", message_type)):
        encoded = value.encode("utf-8")
        headers += bytes([len(name)]) + name.encode("ascii")
        headers += bytes([7]) + struct.pack(">H", len(encoded)) + encoded

    total = 12 + len(headers) + len(body) + 4
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)
    frame = prelude + headers + body
    return frame + struct.pack(">I", binascii.crc32(frame) & 0xFFFFFFFF)


async def _decode(raw: bytes, *, chunk_size: int = 1_000_000, max_bytes: int = 1_000_000):
    async def chunks():
        for start in range(0, len(raw), chunk_size):
            yield raw[start : start + chunk_size]

    return [f async for f in iter_event_stream(chunks(), max_bytes=max_bytes)]


async def test_frames_decode_with_their_headers_and_payload():
    raw = _frame("contentBlockDelta", {"delta": {"text": "hi"}})
    frames = await _decode(raw)

    assert len(frames) == 1
    assert frames[0].event_type == "contentBlockDelta"
    assert frames[0].message_type == "event"
    assert frames[0].json() == {"delta": {"text": "hi"}}


async def test_several_frames_in_one_chunk_all_decode():
    raw = _frame("messageStart", {"role": "assistant"}) + _frame(
        "messageStop", {"stopReason": "end_turn"}
    )
    frames = await _decode(raw)
    assert [f.event_type for f in frames] == ["messageStart", "messageStop"]


async def test_frames_split_across_network_chunks_reassemble():
    """Chunk boundaries have nothing to do with frame boundaries."""
    raw = _frame("contentBlockDelta", {"delta": {"text": "hello world"}}) * 1
    frames = await _decode(raw, chunk_size=7)
    assert len(frames) == 1
    assert frames[0].json()["delta"]["text"] == "hello world"


async def test_a_corrupted_prelude_is_a_protocol_error():
    raw = bytearray(_frame("messageStart", {}))
    raw[9] ^= 0xFF  # flip a bit inside the prelude CRC
    with pytest.raises(StreamProtocolError) as excinfo:
        await _decode(bytes(raw))
    assert "checksum" in str(excinfo.value)


async def test_a_corrupted_payload_is_a_protocol_error():
    raw = bytearray(_frame("contentBlockDelta", {"delta": {"text": "hi"}}))
    raw[-6] ^= 0xFF  # corrupt the payload, leaving the prelude intact
    with pytest.raises(StreamProtocolError) as excinfo:
        await _decode(bytes(raw))
    assert "checksum" in str(excinfo.value)


async def test_a_truncated_stream_is_a_protocol_error():
    raw = _frame("messageStart", {"role": "assistant"})[:-3]
    with pytest.raises(StreamProtocolError) as excinfo:
        await _decode(raw)
    assert "mid-frame" in str(excinfo.value)


async def test_the_byte_cap_is_enforced():
    raw = _frame("contentBlockDelta", {"delta": {"text": "x" * 500}})
    with pytest.raises(StreamProtocolError) as excinfo:
        await _decode(raw, max_bytes=64)
    assert "max_response_bytes" in str(excinfo.value)


async def test_an_exception_frame_is_flagged():
    raw = _frame("throttlingException", {"message": "slow down"}, message_type="exception")
    frames = await _decode(raw)
    assert frames[0].is_exception
    assert frames[0].event_type == "throttlingException"
    assert frames[0].json()["message"] == "slow down"
