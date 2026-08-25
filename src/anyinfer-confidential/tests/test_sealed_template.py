from __future__ import annotations

import pytest

from anyinfer_confidential import (
    KeyRing,
    LicenseError,
    RevokedLicenseError,
    TemplateDecryptionError,
    TemplateVault,
    generate_key,
    generate_signing_keypair,
    issue_license,
    seal_template,
)
from anyinfer_confidential.license import RevocationChecker


def _vault(
    *,
    days: int = 30,
    revocation_checker: RevocationChecker | None = None,
    revocation_fail_closed: bool = False,
) -> tuple[TemplateVault, bytes]:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("dep-1", private_key=private_key, valid_days=days)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}),
        license_public_key=public_key,
        license_blob=blob,
        revocation_checker=revocation_checker,
        revocation_fail_closed=revocation_fail_closed,
    )
    return vault, key


def test_seal_and_render_round_trips_the_plaintext() -> None:
    vault, key = _vault()
    template = seal_template(
        "Hello {name}, welcome to {place}.", key=key, template_id="greet", key_id="k1"
    )
    assert vault.render(template, name="Ada", place="London") == (
        "Hello Ada, welcome to London."
    )


def test_sealed_asset_never_contains_the_plaintext() -> None:
    key = generate_key()
    template = seal_template("a very secret prompt", key=key, template_id="t", key_id="k1")
    assert b"secret" not in template.ciphertext
    assert "secret" not in template.to_json()


def test_wrong_key_fails_to_decrypt() -> None:
    vault, _ = _vault()
    other_key = generate_key()
    template = seal_template("hi {x}", key=other_key, template_id="t", key_id="k1")
    with pytest.raises(TemplateDecryptionError):
        vault.render(template, x="1")


def test_unprovisioned_key_id_fails_to_decrypt() -> None:
    vault, key = _vault()
    template = seal_template("hi {x}", key=key, template_id="t", key_id="unknown-key")
    with pytest.raises(TemplateDecryptionError):
        vault.render(template, x="1")


def test_expired_license_refuses_to_render() -> None:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("dep-1", private_key=private_key, valid_days=-1)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=public_key, license_blob=blob
    )
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    with pytest.raises(LicenseError):
        vault.render(template, x="1")


def test_license_signed_by_a_different_key_is_rejected() -> None:
    key = generate_key()
    _, real_public_key = generate_signing_keypair()
    other_private_key, _ = generate_signing_keypair()
    forged_blob = issue_license("dep-1", private_key=other_private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=real_public_key, license_blob=forged_blob
    )
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    with pytest.raises(LicenseError):
        vault.render(template, x="1")


def test_revocation_check_blocks_a_revoked_deployment() -> None:
    vault, key = _vault(revocation_checker=lambda deployment_id: False)
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    with pytest.raises(RevokedLicenseError):
        vault.render(template, x="1")


def test_revocation_check_allows_a_non_revoked_deployment() -> None:
    vault, key = _vault(revocation_checker=lambda deployment_id: True)
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    assert vault.render(template, x="1") == "hi 1"


def test_revocation_check_failure_fails_open_by_default() -> None:
    def flaky_checker(deployment_id: str) -> bool:
        raise ConnectionError("network unreachable")

    vault, key = _vault(revocation_checker=flaky_checker)
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    # First call: never checked successfully yet -> fails open (renders).
    assert vault.render(template, x="1") == "hi 1"


def test_revocation_check_failure_fails_closed_when_configured() -> None:
    def flaky_checker(deployment_id: str) -> bool:
        raise ConnectionError("network unreachable")

    vault, key = _vault(revocation_checker=flaky_checker, revocation_fail_closed=True)
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    with pytest.raises(RevokedLicenseError):
        vault.render(template, x="1")


def test_revocation_check_failure_after_a_known_revocation_stays_blocked() -> None:
    calls = {"n": 0}

    def sometimes_flaky(deployment_id: str) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # revoked, observed successfully
        raise ConnectionError("network unreachable")  # then the network drops

    vault, key = _vault(revocation_checker=sometimes_flaky)
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    with pytest.raises(RevokedLicenseError):
        vault.render(template, x="1")
    # Second call, network down: must not silently fall back to "allowed" just because
    # the check failed — the last known answer was "revoked."
    with pytest.raises(RevokedLicenseError):
        vault.render(template, x="1")


def test_key_rotation_old_and_new_keys_coexist_in_one_ring() -> None:
    old_key = generate_key()
    new_key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("dep-1", private_key=private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"old": old_key, "new": new_key}),
        license_public_key=public_key,
        license_blob=blob,
    )
    old_template = seal_template("old {x}", key=old_key, template_id="a", key_id="old")
    new_template = seal_template("new {x}", key=new_key, template_id="b", key_id="new")
    assert vault.render(old_template, x="1") == "old 1"
    assert vault.render(new_template, x="1") == "new 1"


def test_encrypted_template_json_round_trip() -> None:
    key = generate_key()
    template = seal_template("hi {x}", key=key, template_id="t", key_id="k1")
    restored = type(template).from_json(template.to_json())
    assert restored == template


def test_the_license_gate_is_a_code_path_not_a_lock_on_the_ciphertext() -> None:
    """Pins Tier 1's stated ceiling in executable form.

    The docs used to say an install without a valid license "cannot produce a single
    rendered prompt". It cannot produce one *through the vault* — but the bundle carries
    both the key and the ciphertext, so a holder can decrypt directly and never reach the
    check. That is inherent to client-side sealing, and it is now stated plainly rather
    than papered over.

    This test exists so the stronger claim cannot quietly come back: if someone ever makes
    license validity enter key derivation, this fails and the docs get revisited with it.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    template = seal_template("Hello {name}", key=key, template_id="greet", key_id="k1")

    # Through the vault, an expired license is refused.
    expired = issue_license("acme", private_key=private_key, valid_days=-1)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=public_key, license_blob=expired
    )
    with pytest.raises(LicenseError):
        vault.render(template, name="world")

    # Holding the same bundle, decryption succeeds without any license at all.
    plaintext = AESGCM(key).decrypt(template.nonce, template.ciphertext, None)
    assert plaintext.decode("utf-8") == "Hello {name}"
