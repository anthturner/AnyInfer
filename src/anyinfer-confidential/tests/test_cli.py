from __future__ import annotations

import os
from pathlib import Path

import pytest

from anyinfer_confidential.cli import main
from anyinfer_confidential.license import verify_license
from anyinfer_confidential.sealed_template import EncryptedTemplate


def test_keygen_writes_a_key_file(tmp_path: Path) -> None:
    out = tmp_path / "key.bin"
    assert main(["keygen", "--out", str(out)]) == 0
    assert out.stat().st_size == 32  # AES-256 key


def test_seal_and_issue_license_end_to_end(tmp_path: Path) -> None:
    key_path = tmp_path / "key.bin"
    assert main(["keygen", "--out", str(key_path)]) == 0

    priv_path = tmp_path / "priv.bin"
    pub_path = tmp_path / "pub.bin"
    assert (
        main(
            [
                "keygen-license",
                "--out-private",
                str(priv_path),
                "--out-public",
                str(pub_path),
            ]
        )
        == 0
    )

    template_path = tmp_path / "template.txt"
    template_path.write_text("Hello {name}")
    sealed_path = tmp_path / "sealed.json"
    assert (
        main(
            [
                "seal",
                str(template_path),
                "--key",
                str(key_path),
                "--key-id",
                "k1",
                "--template-id",
                "greeting",
                "--out",
                str(sealed_path),
            ]
        )
        == 0
    )
    template = EncryptedTemplate.from_json(sealed_path.read_text())
    assert template.template_id == "greeting"
    assert "Hello" not in sealed_path.read_text()

    license_path = tmp_path / "license.bin"
    assert (
        main(
            [
                "issue-license",
                "--private-key",
                str(priv_path),
                "--deployment-id",
                "dep-1",
                "--days",
                "30",
                "--out",
                str(license_path),
            ]
        )
        == 0
    )
    verified = verify_license(license_path.read_bytes(), public_key=pub_path.read_bytes())
    assert verified.deployment_id == "dep-1"


def test_secret_outputs_are_owner_restricted_or_say_they_are_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Owner-only where the platform can express it; a warning where it cannot.

    Skipping this on Windows is what let the gap hide: `chmod(0o600)` there toggles a
    read-only attribute and leaves the ACL untouched, so the key stays readable by every
    other local account while the mode argument implies otherwise. Both branches are
    asserted so neither platform is simply unchecked.
    """
    from anyinfer._private_files import OWNER_ONLY_IS_ENFORCED

    key_path = tmp_path / "key.bin"
    assert main(["keygen", "--out", str(key_path)]) == 0
    assert key_path.exists()

    if OWNER_ONLY_IS_ENFORCED:
        assert key_path.stat().st_mode & 0o777 == 0o600
    else:
        assert "without owner-only permissions" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_secret_outputs_are_written_mode_0600(tmp_path: Path) -> None:
    """Secret outputs are not readable by other local users.

    These are the crown jewels of the confidential tiers: the signing key mints the
    licenses that gate every template decryption, and the AES key decrypts every
    template sealed under its id. A default umask would leave them group- and
    world-readable on a shared build machine or a CI runner.
    """
    key_path = tmp_path / "key.bin"
    assert main(["keygen", "--out", str(key_path)]) == 0

    priv_path = tmp_path / "priv.bin"
    pub_path = tmp_path / "pub.bin"
    assert (
        main(
            ["keygen-license", "--out-private", str(priv_path), "--out-public", str(pub_path)]
        )
        == 0
    )

    license_path = tmp_path / "license.bin"
    assert (
        main(
            [
                "issue-license",
                "--deployment-id",
                "deployment-1",
                "--private-key",
                str(priv_path),
                "--days",
                "30",
                "--out",
                str(license_path),
            ]
        )
        == 0
    )

    for secret in (key_path, priv_path, license_path):
        mode = secret.stat().st_mode & 0o777
        assert mode == 0o600, f"{secret.name} is mode {mode:o}, expected 600"

    # The public verification key is meant to ship with clients; it is not restricted.
    assert pub_path.exists()
