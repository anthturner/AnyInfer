from __future__ import annotations

from pathlib import Path

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
