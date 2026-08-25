"""The contribution path for cassettes: record real traffic, refuse to ship a leaky file.

Recording needs an account, and no maintainer will hold accounts on every supported
provider — so this path exists for contributors, and its safety properties matter more
than its ergonomics. A contributed cassette is a file that a stranger's live API traffic
went into, reviewed by someone who cannot know what was in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from anyinfer.testing.cassettes import Cassette, Interaction
from anyinfer.testing.recording import (
    AuditFinding,
    audit_cassette,
    audit_interaction,
)


def _interaction(**overrides: object) -> Interaction:
    base: dict[str, object] = {
        "method": "POST",
        "url": "https://api.example.test/v1/chat/completions",
        "request_body": '{"model":"m","messages":[]}',
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"choices":[{"message":{"content":"hi"}}]}',
    }
    base.update(overrides)
    return Interaction(**base)  # type: ignore[arg-type]


class TestSecretShapes:
    """What the audit finds, independently of what redaction happened to know about."""

    def test_a_vendor_prefixed_key_in_a_response_body_is_found(self) -> None:
        """Providers echo keys into error messages, and redaction never saw this one."""
        leaky = _interaction(body='{"error":"bad key sk-ant-api03-AAAABBBBCCCCDDDDEEEE"}')
        findings = audit_interaction(leaky)
        assert [f.shape for f in findings] == ["vendor-api-key"]

    def test_a_bearer_token_written_into_a_body_is_found(self) -> None:
        """Header stripping cannot help when the token is in the payload."""
        leaky = _interaction(request_body='{"auth":"Bearer abcdefghijklmnopqrstuvwxyz"}')
        assert any(f.shape == "bearer-token" for f in audit_interaction(leaky))

    def test_a_jwt_is_found(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
        assert any(f.shape == "jwt" for f in audit_interaction(_interaction(body=token)))

    def test_an_aws_access_key_id_is_found(self) -> None:
        leaky = _interaction(body='{"id":"AKIAIOSFODNN7EXAMPLE"}')
        assert any(f.shape == "aws-access-key-id" for f in audit_interaction(leaky))

    def test_private_key_material_is_found(self) -> None:
        leaky = _interaction(request_body="-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        assert any(f.shape == "private-key" for f in audit_interaction(leaky))

    def test_a_credential_named_field_is_found(self) -> None:
        leaky = _interaction(request_body='{"model":"m","api_key":"AAAABBBBCCCCDDDD"}')
        assert any(f.shape == "credential-field" for f in audit_interaction(leaky))

    def test_a_secret_in_a_header_value_is_found(self) -> None:
        """Only the known auth headers are struck wholesale; others keep their values."""
        leaky = _interaction(headers={"x-session": "Bearer abcdefghijklmnopqrstuvwx"})
        findings = audit_interaction(leaky)
        assert findings and findings[0].where == "header:x-session"


class TestFalsePositives:
    """A check that cries wolf gets turned off, so ordinary traffic must stay quiet."""

    def test_an_ordinary_exchange_produces_nothing(self) -> None:
        assert audit_interaction(_interaction()) == []

    def test_a_redacted_placeholder_is_not_a_finding(self) -> None:
        clean = _interaction(headers={"authorization": "[redacted]"})
        assert audit_interaction(clean) == []

    def test_an_embedding_vector_is_not_a_finding(self) -> None:
        """Response bodies are full of long base64 and float runs."""
        vector = ",".join(str(i / 97) for i in range(256))
        assert audit_interaction(_interaction(body=f'{{"embedding":[{vector}]}}')) == []

    def test_a_base64_embedding_payload_is_not_a_finding(self) -> None:
        blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5eg==" * 4
        assert audit_interaction(_interaction(body=f'{{"embedding":"{blob}"}}')) == []

    def test_a_request_id_is_not_a_finding(self) -> None:
        clean = _interaction(body='{"id":"9aa82b66-8985-4d37-b323-062db918d31b"}')
        assert audit_interaction(clean) == []


class TestReporting:
    """A finding printed to a CI log must not itself become the leak."""

    def test_the_excerpt_never_carries_the_whole_secret(self) -> None:
        secret = "sk-ant-api03-" + "Z" * 40
        findings = audit_interaction(_interaction(body=secret))
        assert findings
        for finding in findings:
            assert secret not in finding.excerpt
            assert secret not in str(finding)

    def test_a_finding_names_its_interaction_and_location(self) -> None:
        finding = AuditFinding(3, "body", "jwt", "eyJhbG…9r (64 chars)")
        assert "interaction 3" in str(finding)
        assert "body" in str(finding)


class TestAuditingSavedBytes:
    """The audit reads what would actually be committed, after redaction ran."""

    def test_a_saved_cassette_is_audited_from_disk(self, tmp_path: Path) -> None:
        cassette = Cassette(tmp_path / "provider_default.json")
        cassette.append(_interaction(body='{"error":"key sk-ant-api03-AAAABBBBCCCCDDDD"}'))
        cassette.save()

        findings = audit_cassette(tmp_path / "provider_default.json")
        assert [f.shape for f in findings] == ["vendor-api-key"]

    def test_redaction_running_first_is_what_clears_a_registered_secret(
        self, tmp_path: Path
    ) -> None:
        """The two passes are complementary, not redundant.

        Redaction removes what it was told about; the audit finds credential *shapes* it
        was never told about. This proves the first half: a registered secret is gone from
        the saved bytes, so the audit has nothing to find.
        """
        from anyinfer.redaction import register_secret

        secret = "sk-ant-api03-" + "Q" * 32
        register_secret(secret)
        cassette = Cassette(tmp_path / "provider_registered.json")
        cassette.append(_interaction(request_body=f'{{"key":"{secret}"}}'))
        cassette.save()

        saved = (tmp_path / "provider_registered.json").read_text(encoding="utf-8")
        assert secret not in saved
        assert audit_cassette(tmp_path / "provider_registered.json") == []

    def test_interaction_indexes_survive_the_round_trip(self, tmp_path: Path) -> None:
        cassette = Cassette(tmp_path / "provider_multi.json")
        cassette.append(_interaction())
        cassette.append(_interaction(body='{"error":"AKIAIOSFODNN7EXAMPLE"}'))
        cassette.save()

        findings = audit_cassette(tmp_path / "provider_multi.json")
        assert [f.interaction for f in findings] == [1]

    def test_an_empty_cassette_audits_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"version": 1, "interactions": []}), encoding="utf-8")
        assert audit_cassette(path) == []


class TestRecordingThroughTheCli:
    """`anyinfer conform --record` is the contribution path, end to end."""

    def _config(self, tmp_path: Path) -> Path:
        """A config naming one openai-compat provider, with no credentials in the file."""
        path = tmp_path / "anyinfer.json"
        path.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "providers": [
                        {
                            "id": "openai-compat",
                            "base_url": "https://fake.example.test/v1",
                            "api_key": "env://FAKE_COMPAT_KEY",
                        }
                    ],
                    "default_route": ["openai-compat:fake-model-small"],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_a_run_records_one_cassette_per_scenario_and_they_replay(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """Record against a fake standing in for a live endpoint, then replay offline.

        The point of a cassette is that the second run needs no credentials, so the
        replay half is the half worth asserting.
        """
        import anyinfer as ai
        from anyinfer.cli import main
        from anyinfer.testing.cassettes import Cassette, CassetteTransport
        from anyinfer.testing.fakes import FakeOpenAIServer, scenario_responses

        recorded = tmp_path / "cassettes"
        # One fake per scenario, exactly as a live endpoint would behave per scenario.
        servers = {s: FakeOpenAIServer(scenario_responses(s)) for s in ("default", "structured")}

        original = CassetteTransport.__init__

        def patched(self: object, cassette: object, **kwargs: object) -> None:
            # Stand a fake in for the real network the recorder would otherwise open.
            scenario = Path(cassette.path).stem.split("_", 1)[1]  # type: ignore[attr-defined]
            kwargs["inner"] = servers[scenario].transport()
            original(self, cassette, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(CassetteTransport, "__init__", patched)  # type: ignore[attr-defined]
        monkeypatch.setenv("FAKE_COMPAT_KEY", "sk-live-AAAABBBBCCCCDDDDEEEEFFFF")  # type: ignore[attr-defined]

        code = main(
            [
                "conform",
                "openai-compat",
                "--model",
                "fake-model-small",
                "--config",
                str(self._config(tmp_path)),
                "--record",
                str(recorded),
                "--only",
                "non_streaming",
                "--only",
                "structured_output",
            ]
        )
        assert code == 0

        written = sorted(p.name for p in recorded.glob("*.json"))
        assert written == ["openai-compat_default.json", "openai-compat_structured.json"]

        # The credential reached the wire but must not have reached the file: it was
        # resolved through anyinfer.credentials, so redaction knew about it.
        for path in recorded.glob("*.json"):
            assert "sk-live-AAAABBBBCCCCDDDDEEEEFFFF" not in path.read_text(encoding="utf-8")
            assert audit_cassette(path) == []

        # Replay: no fake, no credential, same answer.
        cassette = Cassette(recorded / "openai-compat_default.json")
        assert cassette.interactions, "the recording captured nothing"

        async def replay() -> str:
            client = ai.AsyncClient(
                [
                    ai.ProviderSettings.of(
                        "openai-compat",
                        base_url="https://fake.example.test/v1",
                        api_key="cassette-replay-key",
                        transport=CassetteTransport(cassette),
                    )
                ],
                use_default_catalog=False,
            )
            try:
                result = await client.generate(
                    "Say hello.", target="openai-compat:fake-model-small"
                )
                return result.text
            finally:
                await client.aclose()

        import asyncio

        assert asyncio.run(replay())

    def test_a_leaky_cassette_is_withheld_rather_than_written(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """The audit blocks the write; it does not warn and leave the file behind.

        A file left on disk after a warning is a file someone commits after skimming
        past the warning.
        """
        from anyinfer.cli import _CassetteRecorder
        from anyinfer.testing.cassettes import Cassette

        recorder = _CassetteRecorder(tmp_path, "example")
        cassette = Cassette(tmp_path / "example_default.json")
        cassette.append(_interaction(body='{"error":"key sk-ant-api03-AAAABBBBCCCCDDDD"}'))
        recorder._cassettes["default"] = cassette

        assert recorder.finish() == 1
        assert not (tmp_path / "example_default.json").exists()
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "WITHHELD" in out
        assert "sk-ant-api03-AAAABBBBCCCCDDDD" not in out, "the report leaked the secret"

    def test_a_scenario_that_recorded_nothing_writes_no_file(self, tmp_path: Path) -> None:
        """An empty cassette on disk would look like coverage that never happened."""
        from anyinfer.cli import _CassetteRecorder
        from anyinfer.testing.cassettes import Cassette

        recorder = _CassetteRecorder(tmp_path, "example")
        recorder._cassettes["skipped"] = Cassette(tmp_path / "example_skipped.json")

        assert recorder.finish() == 0
        assert not (tmp_path / "example_skipped.json").exists()
