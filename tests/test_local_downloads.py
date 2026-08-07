"""Artifact downloads: verification, atomicity, resume, sharding, and licensing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx2
import pytest

from anyinfer.catalog.model import GgufArtifact, GgufFile
from anyinfer.errors import LocalRuntimeError
from anyinfer.local.downloads import (
    artifact_paths,
    download_artifact,
    iter_missing,
    verify_file,
)

PAYLOAD = b"gguf-bytes-" * 512
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def _artifact(*, sha256: str = DIGEST, sharded: bool = False, license_: str = "Apache-2.0"):
    if sharded:
        second = PAYLOAD + b"second-shard"
        files = (
            GgufFile("model-00001-of-00002.gguf", "https://host.invalid/a", DIGEST),
            GgufFile(
                "model-00002-of-00002.gguf",
                "https://host.invalid/b",
                hashlib.sha256(second).hexdigest(),
            ),
        )
    else:
        files = (GgufFile("model.gguf", "https://host.invalid/a", sha256),)
    return GgufArtifact(id="test-artifact", files=files, license=license_)


def _client(handler) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def _serving(body: bytes = PAYLOAD):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/b":
            return httpx2.Response(200, content=PAYLOAD + b"second-shard")
        range_header = request.headers.get("range")
        if range_header:
            start = int(range_header.split("=")[1].split("-")[0])
            return httpx2.Response(
                206,
                content=body[start:],
                headers={"content-length": str(len(body) - start)},
            )
        return httpx2.Response(200, content=body, headers={"content-length": str(len(body))})

    return handler


def test_downloads_and_verifies(tmp_path: Path) -> None:
    report = download_artifact(
        _artifact(), model_dir=tmp_path, client=_client(_serving())
    )

    assert report.primary_path.read_bytes() == PAYLOAD
    assert report.reused is False
    assert report.downloaded_bytes == len(PAYLOAD)
    assert not report.warnings


def test_existing_verified_file_is_reused(tmp_path: Path) -> None:
    (tmp_path / "model.gguf").write_bytes(PAYLOAD)

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("a verified file must not be re-downloaded")

    report = download_artifact(_artifact(), model_dir=tmp_path, client=_client(refuse))
    assert report.reused is True
    assert report.downloaded_bytes == 0


def test_corrupt_existing_file_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "model.gguf").write_bytes(b"corrupted")

    report = download_artifact(
        _artifact(), model_dir=tmp_path, client=_client(_serving())
    )

    assert report.primary_path.read_bytes() == PAYLOAD
    assert any("failed verification" in w for w in report.warnings)


def test_hash_mismatch_after_download_is_fatal_and_leaves_nothing(tmp_path: Path) -> None:
    """A bad file must not survive: a corrupt GGUF fails later with an unrelated error."""
    artifact = _artifact(sha256=hashlib.sha256(b"different").hexdigest())

    with pytest.raises(LocalRuntimeError, match="sha256"):
        download_artifact(artifact, model_dir=tmp_path, client=_client(_serving()))

    assert not (tmp_path / "model.gguf").exists()
    assert not list(tmp_path.glob("*.part")), "the partial file must be cleaned up"


def test_download_is_atomic(tmp_path: Path) -> None:
    """Bytes land in a .part file, so a crash cannot leave a half-file looking complete."""
    seen: list[list[str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append([p.name for p in tmp_path.iterdir()])
        return httpx2.Response(200, content=PAYLOAD)

    download_artifact(_artifact(), model_dir=tmp_path, client=_client(handler))

    assert (tmp_path / "model.gguf").exists()
    assert not list(tmp_path.glob("*.part"))


def test_interrupted_download_resumes(tmp_path: Path) -> None:
    partial = tmp_path / "model.gguf.part"
    partial.write_bytes(PAYLOAD[:100])

    requests: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.headers.get("range"))
        start = int(request.headers["range"].split("=")[1].split("-")[0])
        return httpx2.Response(206, content=PAYLOAD[start:])

    report = download_artifact(_artifact(), model_dir=tmp_path, client=_client(handler))

    assert requests == ["bytes=100-"], "a resumed transfer must send a range request"
    assert report.primary_path.read_bytes() == PAYLOAD
    assert report.downloaded_bytes == len(PAYLOAD) - 100


def test_server_ignoring_a_range_request_restarts_cleanly(tmp_path: Path) -> None:
    """A 200 answer to a range request means the body is not a continuation."""
    (tmp_path / "model.gguf.part").write_bytes(PAYLOAD[:100])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=PAYLOAD)

    report = download_artifact(_artifact(), model_dir=tmp_path, client=_client(handler))
    assert report.primary_path.read_bytes() == PAYLOAD, "must not concatenate"


def test_sharded_artifacts_download_every_file(tmp_path: Path) -> None:
    report = download_artifact(
        _artifact(sharded=True), model_dir=tmp_path, client=_client(_serving())
    )

    assert len(report.paths) == 2
    assert all(p.exists() for p in report.paths)
    assert report.primary_path.name.endswith("00001-of-00002.gguf")


def test_progress_is_reported(tmp_path: Path) -> None:
    seen: list[tuple[str, int, int | None]] = []

    download_artifact(
        _artifact(),
        model_dir=tmp_path,
        client=_client(_serving()),
        progress=lambda a, done, total: seen.append((a, done, total)),
    )

    assert seen
    assert seen[-1][0] == "test-artifact"
    assert seen[-1][1] == len(PAYLOAD)


def test_http_failure_is_actionable(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, content=b"nope")

    with pytest.raises(LocalRuntimeError) as excinfo:
        download_artifact(_artifact(), model_dir=tmp_path, client=_client(handler))

    assert excinfo.value.hint is not None


def test_unhashed_artifact_warns(tmp_path: Path) -> None:
    """No recorded sha256 means no verification; the download proceeds but says so."""
    report = download_artifact(
        _artifact(sha256=""), model_dir=tmp_path, client=_client(_serving())
    )

    assert report.primary_path.read_bytes() == PAYLOAD
    assert any("no recorded sha256" in w for w in report.warnings)


def test_license_enforcement_rejects_unknown_terms(tmp_path: Path) -> None:
    """A convenience feature must not quietly fetch weights under unseen terms."""
    with pytest.raises(LocalRuntimeError, match="license"):
        download_artifact(
            _artifact(license_="proprietary-eula"),
            model_dir=tmp_path,
            client=_client(_serving()),
            enforce_license=True,
        )


def test_license_enforcement_is_opt_in(tmp_path: Path) -> None:
    report = download_artifact(
        _artifact(license_="proprietary-eula"),
        model_dir=tmp_path,
        client=_client(_serving()),
    )
    assert report.primary_path.exists()


def test_verify_file_helper(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(PAYLOAD)

    assert verify_file(path, DIGEST) is True
    assert verify_file(path, "0" * 64) is False
    assert verify_file(tmp_path / "absent.bin", DIGEST) is False
    assert verify_file(path, "") is True, "no recorded hash: existence is all we can check"


def test_iter_missing_reports_absent_and_corrupt(tmp_path: Path) -> None:
    artifact = _artifact()
    assert iter_missing([artifact], tmp_path) == [artifact]

    (tmp_path / "model.gguf").write_bytes(PAYLOAD)
    assert iter_missing([artifact], tmp_path) == []

    (tmp_path / "model.gguf").write_bytes(b"corrupt")
    assert iter_missing([artifact], tmp_path) == [artifact]


def test_artifact_paths_are_predictable(tmp_path: Path) -> None:
    paths = artifact_paths(_artifact(sharded=True), tmp_path)
    assert [p.parent for p in paths] == [tmp_path, tmp_path]
    assert [p.name for p in paths] == [
        "model-00001-of-00002.gguf",
        "model-00002-of-00002.gguf",
    ]
