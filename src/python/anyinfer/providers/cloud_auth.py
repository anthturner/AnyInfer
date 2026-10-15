"""Cloud-provider authentication: AWS SigV4 and Google OAuth access tokens.

The two enterprise providers (Bedrock, Vertex AI) authenticate with signed requests rather
than a static key, which is the one genuinely new piece of infrastructure they need. Both
flows are implemented here against the standard library and ``httpx2`` alone, so the slim
core is unchanged and ``pip install anyinfer`` still pulls exactly two dependencies.

**Credentials are resolved in precedence order**, and the first rung is always "the caller
already has one":

1. **An explicit token or key** on ``ProviderSettings`` — a Bedrock API key, a
   ``gcloud auth print-access-token`` value. Nothing is signed or fetched.
2. **The official SDK**, when the application happens to have it installed. ``boto3`` and
   ``google-auth`` know about instance metadata, SSO caches, and profile chains that no
   reimplementation should try to replicate, so if they are importable they win.
3. **The hand-rolled flow** — SigV4 from static AWS keys, or a signed JWT exchanged for a
   Google access token. Enough to work from environment variables or a service-account
   file with no extra install.

Tokens are cached until shortly before they expire, because acquiring one costs a round
trip that would otherwise be paid on every request.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ConfigError, CredentialError

__all__ = [
    "GOOGLE_CLOUD_SCOPE",
    "AwsCredentials",
    "GoogleTokenSource",
    "resolve_aws_credentials",
    "sigv4_headers",
]

GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
"""The scope Vertex AI requires, per Google's documentation."""

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_TOKEN_LIFETIME_S = 3600
_REFRESH_MARGIN_S = 120
"""Refresh this long before expiry, so a token cannot lapse mid-request."""

_SIGV4_ALGORITHM = "AWS4-HMAC-SHA256"
_UNSIGNED_PAYLOAD_HEADERS = frozenset({"authorization", "content-length", "expect"})
"""Headers excluded from the signature because proxies routinely rewrite them."""


# ---- AWS SigV4 -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AwsCredentials:
    """An AWS access key, with an optional session token for temporary credentials."""

    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


def resolve_aws_credentials(options: Mapping[str, Any]) -> AwsCredentials | None:
    """Find AWS credentials, preferring the SDK's chain over environment variables.

    Args:
        options: Provider options, which may carry explicit
            ``aws_access_key_id``/``aws_secret_access_key``/``aws_session_token``, or a
            ``profile`` to look up through ``boto3``.

    Returns:
        The credentials, or ``None`` when none could be found — the caller decides
        whether that is fatal, since a Bedrock API key needs no credentials at all.
    """
    explicit = options.get("aws_access_key_id")
    if isinstance(explicit, str) and explicit:
        secret = options.get("aws_secret_access_key")
        if not isinstance(secret, str) or not secret:
            raise ConfigError(
                "aws_access_key_id was supplied without aws_secret_access_key",
                hint="supply both, or neither to use the default credential chain",
            )
        token = options.get("aws_session_token")
        return AwsCredentials(explicit, secret, token if isinstance(token, str) else None)

    # boto3 knows about SSO caches, instance metadata, and profile chains. If the
    # application already has it, deferring is strictly better than reimplementing.
    resolved = _aws_credentials_from_boto3(options)
    if resolved is not None:
        return resolved

    key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if key and secret:
        return AwsCredentials(key, secret, os.environ.get("AWS_SESSION_TOKEN"))
    return None


def _aws_credentials_from_boto3(options: Mapping[str, Any]) -> AwsCredentials | None:
    """Ask ``boto3`` for credentials, or return ``None`` when it is absent or empty."""
    try:
        import boto3
    except ImportError:
        return None
    try:
        profile = options.get("profile")
        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        frozen = session.get_credentials()
        if frozen is None:
            return None
        frozen = frozen.get_frozen_credentials()
    except Exception:  # noqa: BLE001 — a misconfigured SDK must not block the fallbacks
        return None
    return AwsCredentials(frozen.access_key, frozen.secret_key, frozen.token)


def sigv4_headers(
    *,
    credentials: AwsCredentials,
    method: str,
    url: str,
    region: str,
    service: str,
    body: bytes,
    headers: Mapping[str, str],
    now: dt.datetime | None = None,
) -> dict[str, str]:
    """Sign a request with AWS Signature Version 4.

    Args:
        credentials: The access key to sign with.
        method: HTTP method, uppercase.
        url: The absolute request URL, including any query string.
        region: AWS region the request targets.
        service: Signing service name (``bedrock`` for the Bedrock runtime).
        body: The exact request body bytes that will be sent.
        headers: Headers to sign alongside ``host`` and the date.
        now: Signing time; injected by tests, otherwise the current UTC time.

    Returns:
        The headers to add to the request: ``authorization``, ``x-amz-date``, the payload
        hash, and a session token when the credentials carry one.
    """
    moment = now or dt.datetime.now(dt.UTC)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = moment.strftime("%Y%m%d")

    parsed = urllib.parse.urlsplit(url)
    payload_hash = hashlib.sha256(body).hexdigest()

    signed: dict[str, str] = {
        k.lower(): " ".join(str(v).split())
        for k, v in headers.items()
        if k.lower() not in _UNSIGNED_PAYLOAD_HEADERS
    }
    signed["host"] = parsed.netloc
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_hash
    if credentials.session_token:
        signed["x-amz-security-token"] = credentials.session_token

    signed_header_names = sorted(signed)
    canonical_headers = "".join(f"{name}:{signed[name]}\n" for name in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_request = "\n".join(
        [
            method.upper(),
            _canonical_path(parsed.path),
            _canonical_query(parsed.query),
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            _SIGV4_ALGORITHM,
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    signing_key = _signing_key(credentials.secret_access_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    result = {
        "authorization": (
            f"{_SIGV4_ALGORITHM} "
            f"Credential={credentials.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        ),
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }
    if credentials.session_token:
        result["x-amz-security-token"] = credentials.session_token
    return result


def _canonical_path(path: str) -> str:
    """Normalize a URI path for signing.

    Each segment is percent-encoded once more than it already is, because the Bedrock
    runtime's paths carry model ids containing colons and dots that must match byte for
    byte between the canonical request and the wire.
    """
    if not path:
        return "/"
    segments = [urllib.parse.quote(segment, safe="-._~") for segment in path.split("/")]
    return "/".join(segments)


def _canonical_query(query: str) -> str:
    """Sort and re-encode a query string, as the signing rules require."""
    if not query:
        return ""
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    encoded = [
        (urllib.parse.quote(k, safe="-._~"), urllib.parse.quote(v, safe="-._~")) for k, v in pairs
    ]
    encoded.sort()
    return "&".join(f"{k}={v}" for k, v in encoded)


def _signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive the date/region/service-scoped signing key."""

    def sign(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    key = sign(f"AWS4{secret}".encode(), date_stamp)
    key = sign(key, region)
    key = sign(key, service)
    return sign(key, "aws4_request")


# ---- Google OAuth ----------------------------------------------------------------------


class GoogleTokenSource:
    """Supplies Google Cloud access tokens, caching them until they near expiry.

    Resolution order matches the module's contract: an explicit token, then
    ``google-auth`` if installed (it understands metadata servers, gcloud's user
    credentials, and workload identity), then a service-account JSON file signed and
    exchanged in-house.

    Args:
        explicit_token: A pre-acquired access token. Used verbatim and never refreshed —
            the caller owns its lifetime.
        options: Provider options, consulted for ``credentials_file`` and ``scope``.
        transport: Test seam — an ``httpx2`` transport for the token exchange.
        proxy: Proxy URL for the token exchange, from the provider instance's settings.
        verify: TLS verification for the token exchange, from the same settings.
        client_cert: Client certificate for the token exchange, from the same settings.

    Note:
        The connection settings are threaded here rather than left to the environment
        because the data plane already honors them per instance. A Vertex instance
        configured with a corporate CA behind an intercepting proxy would otherwise have
        ``generateContent`` succeed and its token exchange fail TLS verification — one
        instance, two different trust decisions, for no reason a user could infer. As on
        the data plane, they are ignored when a `transport` is supplied.
    """

    def __init__(
        self,
        *,
        explicit_token: str | None = None,
        options: Mapping[str, Any] | None = None,
        transport: Any | None = None,
        proxy: str | None = None,
        verify: str | bool | None = None,
        client_cert: str | tuple[str, str] | tuple[str, str, str] | None = None,
    ) -> None:
        self._explicit = explicit_token
        self._options = dict(options or {})
        self._transport = transport
        self._proxy = proxy
        self._verify = verify
        self._client_cert = client_cert
        self._scope = str(self._options.get("scope") or GOOGLE_CLOUD_SCOPE)
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def token(self) -> str:
        """Return a valid access token, acquiring or refreshing one when needed.

        Raises:
            CredentialError: When no credential source could produce a token.
        """
        if self._explicit:
            return self._explicit
        with self._lock:
            if self._token and time.time() < self._expires_at - _REFRESH_MARGIN_S:
                return self._token
            token, lifetime = self._acquire()
            self._token = token
            self._expires_at = time.time() + lifetime
            return token

    def _acquire(self) -> tuple[str, float]:
        """Acquire a token from the strongest available source."""
        from_sdk = self._from_google_auth()
        if from_sdk is not None:
            return from_sdk
        return self._from_service_account_file()

    def _from_google_auth(self) -> tuple[str, float] | None:
        """Use ``google-auth`` when the application has it installed."""
        try:
            import google.auth
            import google.auth.transport.requests
        except ImportError:
            return None
        try:
            credentials, _ = google.auth.default(scopes=[self._scope])
            credentials.refresh(google.auth.transport.requests.Request())
        except Exception:  # noqa: BLE001 — fall through to the hand-rolled flow
            return None
        token = getattr(credentials, "token", None)
        if not isinstance(token, str) or not token:
            return None
        return token, _TOKEN_LIFETIME_S

    def _from_service_account_file(self) -> tuple[str, float]:
        """Sign a JWT with a service-account key and exchange it for an access token.

        Raises:
            CredentialError: When no key file is configured or readable, when it lacks a
                usable private key, or when the exchange fails.
        """
        path = self._options.get("credentials_file") or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        if not path:
            raise CredentialError(
                "no Google Cloud credentials found for this provider",
                hint=(
                    "set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file, "
                    "pass options={'credentials_file': ...}, install google-auth, or "
                    "supply a pre-acquired token as api_key "
                    "(gcloud auth print-access-token)"
                ),
            )

        try:
            info = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise CredentialError(
                f"could not read the Google credentials file: {exc}",
                hint="check the path and its permissions",
            ) from exc
        except ValueError as exc:
            raise CredentialError(f"the Google credentials file is not valid JSON: {exc}") from exc

        assertion = self._signed_assertion(info)
        return self._exchange(assertion)

    def _signed_assertion(self, info: Mapping[str, Any]) -> str:
        """Build and RS256-sign the JWT a service account exchanges for a token."""
        client_email = info.get("client_email")
        private_key = info.get("private_key")
        if not isinstance(client_email, str) or not isinstance(private_key, str):
            raise CredentialError(
                "the Google credentials file is not a service-account key",
                hint="export a service-account JSON key, or install google-auth",
            )

        issued = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": client_email,
            "scope": self._scope,
            "aud": _GOOGLE_TOKEN_URL,
            "iat": issued,
            "exp": issued + _TOKEN_LIFETIME_S,
        }
        signing_input = b".".join(
            (_b64url(json.dumps(header).encode()), _b64url(json.dumps(claims).encode()))
        )
        signature = _rs256_sign(signing_input, private_key)
        return b".".join((signing_input, _b64url(signature))).decode("ascii")

    def _exchange(self, assertion: str) -> tuple[str, float]:
        """Trade a signed assertion for an access token.

        Raises:
            CredentialError: When the token endpoint refuses the assertion.
        """
        import httpx2

        # Passed only when set, and only without a transport, matching `build_client`:
        # httpx distinguishes "not supplied" from an explicit `None`/`False`, and
        # forwarding a default would override its own environment-variable handling.
        # `tls_kwargs` is shared with the data plane so the token exchange resolves a
        # CA bundle and a client certificate exactly the way generation does.
        from .http import tls_kwargs

        tls: dict[str, Any] = {}
        if self._transport is None:
            if self._proxy is not None:
                tls["proxy"] = self._proxy
            tls.update(tls_kwargs(self._verify, self._client_cert))

        with httpx2.Client(transport=self._transport, timeout=30.0, **tls) as client:
            response = client.post(
                _GOOGLE_TOKEN_URL,
                data={"grant_type": _JWT_BEARER_GRANT, "assertion": assertion},
            )
        if response.status_code >= 400:
            raise CredentialError(
                f"Google rejected the token request (HTTP {response.status_code})",
                hint="check the service account's key, scopes, and IAM roles",
            )
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise CredentialError("Google's token response carried no access token")
        expires_in = payload.get("expires_in")
        lifetime = float(expires_in) if isinstance(expires_in, int | float) else _TOKEN_LIFETIME_S
        return token, lifetime


def _b64url(raw: bytes) -> bytes:
    """Base64url-encode without padding, as JWT requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _rs256_sign(message: bytes, private_key_pem: str) -> bytes:
    """RS256-sign a JWT payload.

    Raises:
        CredentialError: When no RSA implementation is available. Signing needs real
            asymmetric crypto, which the standard library does not provide, so this is
            the one path where an optional dependency is genuinely required, and the
            error says exactly which and why.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:
        raise CredentialError(
            "signing a Google service-account assertion requires an RSA implementation",
            hint=(
                "pip install 'anyinfer[vertex]' (or google-auth), or supply a "
                "pre-acquired token as api_key (gcloud auth print-access-token)"
            ),
        ) from exc

    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signer = getattr(key, "sign", None)
    if signer is None:
        raise CredentialError("the service-account key is not an RSA private key")
    signature: bytes = signer(message, padding.PKCS1v15(), hashes.SHA256())
    return signature
