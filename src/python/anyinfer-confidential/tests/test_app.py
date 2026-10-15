"""The Relay's HTTP surface authenticates before it hands back decrypted prompt IP.

The response body of ``POST /v1/relay/assemble`` is the assembled prompt — the exact
material Tier 2 exists to protect. These tests pin the boundary that makes
`RelayRegistry`'s per-tenant scoping mean something: the tenant comes from the presented
bearer token, never from the request body.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from anyinfer_confidential import (
    KeyRing,
    TemplateVault,
    generate_key,
    generate_signing_keypair,
    issue_license,
    seal_template,
)
from anyinfer_confidential.app import build_app
from anyinfer_confidential.relay import (
    Relay,
    RelayError,
    RelayRegistry,
    RelayRoute,
    load_registry,
)

ACME_TOKEN = "acme-token-value"
OTHER_TOKEN = "other-token-value"


def _relay() -> Relay:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=public_key, license_blob=blob
    )
    template = seal_template(
        "Summarize this for {audience}", key=key, template_id="summarize", key_id="k1"
    )
    registry = RelayRegistry()
    registry.register(
        "acme",
        RelayRoute(routing_key="summarize", template=template, target="ollama:qwen3:8b"),
    )
    return Relay(vault=vault, registry=registry)


def _client() -> TestClient:
    tokens = {ACME_TOKEN: "acme", OTHER_TOKEN: "other"}
    # These tests are about authentication, not capacity. `build_app` warns when a
    # multi-tenant relay has no admission limits — deliberately, since that is the
    # noisy-neighbour gap — and `filterwarnings = ["error"]` would turn it into a failure
    # here. The warning has its own coverage in test_app_throttling.py.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return TestClient(build_app(_relay(), tokens=tokens))


def test_building_an_app_without_tokens_is_refused() -> None:
    """There is no unauthenticated mode to reach by omission."""
    with pytest.raises(ValueError, match="at least one bearer token"):
        build_app(_relay(), tokens={})


def test_a_request_without_a_token_gets_nothing() -> None:
    response = _client().post(
        "/v1/relay/assemble",
        json={"routing_key": "summarize", "slots": {"audience": "engineers"}},
    )
    assert response.status_code == 401
    assert "assembled_prompt" not in response.text
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_a_bad_token_gets_nothing() -> None:
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"routing_key": "summarize"},
    )
    assert response.status_code == 401
    assert "assembled_prompt" not in response.text


def test_a_non_ascii_token_is_a_401_not_a_500() -> None:
    """`compare_digest` on str raises `TypeError` above U+007F; bytes never do.

    Starlette decodes header values as latin-1, so any byte >= 0x80 in the Authorization
    value reaches `_authenticate` as a non-ASCII str. Comparing str would raise, and an
    unhandled exception is a 500 that an unauthenticated client can mint at will.
    """
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": b"Bearer t\xf8k\xe9n-\xfe"},
        json={"routing_key": "summarize"},
    )
    assert response.status_code == 401
    assert "assembled_prompt" not in response.text


def test_an_authenticated_request_assembles_for_its_own_tenant() -> None:
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={"routing_key": "summarize", "slots": {"audience": "engineers"}},
    )
    assert response.status_code == 200
    assert response.json()["assembled_prompt"] == "Summarize this for engineers"


def test_the_body_cannot_declare_a_different_tenant() -> None:
    """The pre-fix hole: a caller naming another tenant's id received its prompt."""
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
        json={"tenant_id": "acme", "routing_key": "summarize"},
    )
    assert response.status_code == 403
    assert "assembled_prompt" not in response.text


def test_a_token_cannot_reach_another_tenants_route() -> None:
    """Even without spoofing the body, the other tenant's namespace stays empty."""
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
        json={"routing_key": "summarize"},
    )
    assert response.status_code == 404
    assert "assembled_prompt" not in response.text


def test_a_matching_body_tenant_id_is_accepted() -> None:
    """Agreeing with the token is redundant, not an error — old clients keep working."""
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={
            "tenant_id": "acme",
            "routing_key": "summarize",
            "slots": {"audience": "engineers"},
        },
    )
    assert response.status_code == 200


def test_forward_mode_is_refused_with_an_explanation_not_a_404() -> None:
    """It used to 404 via RelayError, which read as 'no such route'."""
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={"routing_key": "summarize", "mode": "forward"},
    )
    assert response.status_code == 400
    assert "assembles only" in response.json()["error"]


def test_an_oversized_body_is_refused_with_413() -> None:
    """Post-auth exposure only, but one tenant must not exhaust the process for the rest."""
    tokens = {ACME_TOKEN: "acme", OTHER_TOKEN: "other"}
    with warnings.catch_warnings():  # see _client(): the admission warning is not
        warnings.simplefilter("ignore")  # what this test is about
        client = TestClient(build_app(_relay(), tokens=tokens, max_request_bytes=1024))

    response = client.post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={"routing_key": "summarize", "slots": {"audience": "x" * 4096}},
    )
    assert response.status_code == 413


def test_the_body_cap_can_be_disabled() -> None:
    tokens = {ACME_TOKEN: "acme", OTHER_TOKEN: "other"}
    with warnings.catch_warnings():  # see _client(): the admission warning is not
        warnings.simplefilter("ignore")  # what this test is about
        client = TestClient(build_app(_relay(), tokens=tokens, max_request_bytes=0))

    response = client.post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={"routing_key": "summarize", "slots": {"audience": "x" * 4096}},
    )
    assert response.status_code == 200


def test_a_malformed_body_is_a_400() -> None:
    response = _client().post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={"slots": {}},
    )
    assert response.status_code == 400


def test_load_registry_provisions_routes_from_a_file(tmp_path: Path) -> None:
    key = generate_key()
    template = seal_template("Hello {name}", key=key, template_id="greet", key_id="k1")
    document = {
        "tenants": {
            "acme": [
                {
                    "routing_key": "greet",
                    "target": "ollama:qwen3:8b",
                    "template": json.loads(template.to_json()),
                }
            ]
        }
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    registry = load_registry(path)
    route = registry.resolve("acme", "greet")
    assert route.target == "ollama:qwen3:8b"

    with pytest.raises(RelayError):
        registry.resolve("other", "greet")


def test_load_registry_rejects_a_malformed_file(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"tenants": {"acme": [{"routing_key": "greet"}]}}), "utf-8")
    with pytest.raises(RelayError, match="malformed route"):
        load_registry(path)
