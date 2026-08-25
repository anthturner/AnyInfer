"""``anyinfer-confidential`` — the build-time CLI for Tier 1's seal step and license issuance.

No subcommand touches the network or a Relay deployment; every operation here is a local,
offline file transform, matching Tier 1's "no daemon" posture.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from anyinfer._private_files import (
    OWNER_ONLY_IS_ENFORCED,
    owner_only_warning,
    restrict_to_owner,
)

from .license import generate_signing_keypair, issue_license
from .sealed_template import generate_key, seal_template


def _write_private_bytes(path: str, payload: bytes) -> None:
    """Write secret material owner-restricted, created that way before the first byte.

    Writing first and tightening afterwards leaves a window in which the key is
    world-readable, which is exactly what this guards against on a shared build machine
    or a CI runner. Mirrors ``anyinfer.serve.service.write_service``'s token handling.

    **On Windows the restriction cannot be applied.** `chmod` there toggles a read-only
    attribute and leaves the ACL alone, so the file stays readable by every other local
    account while `stat` reports 0o666. This writes the key anyway — a keygen that
    refused to run on Windows would be worse — but says so on stderr rather than letting
    the mode argument imply a protection that is not there. The sidecar's service writer
    takes the stronger line for its bearer token and declines to write a file at all;
    that option is not open here, because the key *is* the artifact being produced.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # `O_BINARY` because `payload` is key material: on Windows `os.open` defaults to text
    # mode, which would rewrite any 0x0A byte in a key as CRLF and corrupt it on write.
    # The flag does not exist on POSIX, where there is no translation to disable.
    descriptor = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    if not restrict_to_owner(target):
        print(owner_only_warning(target, what="key material"), file=sys.stderr)


def _mode_note() -> str:
    """How to describe the permissions actually applied, per platform."""
    return "mode 0600" if OWNER_ONLY_IS_ENFORCED else "NOT owner-restricted on Windows"


def _cmd_keygen(args: argparse.Namespace) -> int:
    key = generate_key()
    _write_private_bytes(args.out, key)
    print(f"wrote AES-256-GCM key to {args.out} ({_mode_note()} — this key decrypts every")
    print("template sealed under its key id; keep it out of source control)")
    return 0


def _cmd_keygen_license(args: argparse.Namespace) -> int:
    private_key, public_key = generate_signing_keypair()
    _write_private_bytes(args.out_private, private_key)
    Path(args.out_public).write_bytes(public_key)
    print(f"wrote license signing keypair to {args.out_private} (private, {_mode_note()},")
    print("                              keep secret — it mints licenses)")
    print(f"                              and {args.out_public} (public, ship with clients)")
    return 0


def _cmd_seal(args: argparse.Namespace) -> int:
    plaintext = Path(args.input).read_text(encoding="utf-8")
    key = Path(args.key).read_bytes()
    template = seal_template(
        plaintext, key=key, template_id=args.template_id, key_id=args.key_id
    )
    Path(args.out).write_text(template.to_json(), encoding="utf-8")
    print(f"sealed {args.input!r} -> {args.out!r} (template_id={args.template_id!r})")
    return 0


def _cmd_issue_license(args: argparse.Namespace) -> int:
    private_key = Path(args.private_key).read_bytes()
    blob = issue_license(args.deployment_id, private_key=private_key, valid_days=args.days)
    _write_private_bytes(args.out, blob)
    print(
        f"issued a {args.days}-day license for {args.deployment_id!r} -> {args.out!r} "
        f"({_mode_note()})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI's argument parser (also used by tests, without invoking `main`)."""
    parser = argparse.ArgumentParser(prog="anyinfer-confidential")
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="generate a template-sealing key")
    p_keygen.add_argument("--out", required=True, help="path to write the key to")
    p_keygen.set_defaults(func=_cmd_keygen)

    p_keygen_lic = sub.add_parser(
        "keygen-license", help="generate a license-signing Ed25519 keypair"
    )
    p_keygen_lic.add_argument("--out-private", required=True)
    p_keygen_lic.add_argument("--out-public", required=True)
    p_keygen_lic.set_defaults(func=_cmd_keygen_license)

    p_seal = sub.add_parser("seal", help="seal a plaintext template into an encrypted asset")
    p_seal.add_argument("input", help="path to the plaintext template file")
    p_seal.add_argument("--key", required=True, help="path to the sealing key")
    p_seal.add_argument("--key-id", required=True, help="identifier for the sealing key")
    p_seal.add_argument("--template-id", required=True, help="identifier for this template")
    p_seal.add_argument("--out", required=True, help="path to write the sealed asset to")
    p_seal.set_defaults(func=_cmd_seal)

    p_issue = sub.add_parser("issue-license", help="issue a signed, time-boxed license blob")
    p_issue.add_argument("--private-key", required=True, help="path to the signing private key")
    p_issue.add_argument("--deployment-id", required=True)
    p_issue.add_argument("--days", type=int, required=True, help="validity period in days")
    p_issue.add_argument("--out", required=True, help="path to write the license blob to")
    p_issue.set_defaults(func=_cmd_issue_license)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
