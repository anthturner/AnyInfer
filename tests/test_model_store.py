"""The model store and the acquisition engine.

No network anywhere: a fake Hugging Face API and a fake CDN are served through
``httpx2.MockTransport``, exactly as the artifact-download tests do. What is under test is
the *accounting* — aggregate progress, resume arithmetic, verification, containment, and
the rule that a half-complete file set is never registered.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx2
import pytest

from anyinfer.errors import ConfigError, LocalRuntimeError
from anyinfer.local.acquire import (
    AcquisitionRequest,
    acquire,
    launch_hints_for,
    plan_acquisition,
)
from anyinfer.local.sources import SourceRef, safe_relative_path
from anyinfer.local.sources.huggingface import HuggingFaceResolver, trusted_redirect
from anyinfer.local.store import ModelStore, StoredFile, StoreEntry, placement_for

SHARD_BYTES = 256 * 1024
COMMIT = "a" * 40


def _shard(index: int) -> bytes:
    """Deterministic, distinct content per shard."""
    return bytes([index]) * SHARD_BYTES


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _shard_name(index: int, count: int = 4) -> str:
    return f"model-{index:05d}-of-{count:05d}.gguf"


def _tree(count: int = 4) -> list[dict[str, object]]:
    return [
        {
            "type": "file",
            "path": _shard_name(i, count),
            "size": SHARD_BYTES,
            "oid": "0" * 40,
            "lfs": {"oid": _digest(_shard(i)), "size": SHARD_BYTES},
        }
        for i in range(1, count + 1)
    ]


def _hf_transport(
    *,
    count: int = 4,
    corrupt: int | None = None,
    tree: list[dict[str, object]] | None = None,
    seen: list[httpx2.Request] | None = None,
) -> httpx2.MockTransport:
    """A fake Hugging Face API plus a *different-origin* CDN for file bodies."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path.endswith("/revision/main"):
            return httpx2.Response(200, json={"sha": COMMIT})
        if "/tree/" in path:
            return httpx2.Response(200, json=tree if tree is not None else _tree(count))
        if "/resolve/" in path:
            if request.url.host == "huggingface.co":
                # The real API redirects file bodies to a CDN on another host.
                name = path.rsplit("/", 1)[-1]
                return httpx2.Response(
                    302, headers={"location": f"https://cdn.invalid/blob/{name}"}
                )
            raise AssertionError("resolve should only be served by the API host")
        if request.url.host == "cdn.invalid":
            name = path.rsplit("/", 1)[-1]
            index = int(name.split("-")[1])
            body = _shard(index)
            if corrupt is not None and index == corrupt:
                body = b"x" * SHARD_BYTES
            start = 0
            range_header = request.headers.get("range")
            if range_header:
                start = int(range_header.split("=")[1].split("-")[0])
                return httpx2.Response(
                    206,
                    content=body[start:],
                    headers={"content-length": str(len(body) - start)},
                )
            return httpx2.Response(200, content=body, headers={"content-length": str(len(body))})
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx2.MockTransport(handler)


def _client(transport: httpx2.MockTransport) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=transport)


def _request(**overrides: object) -> AcquisitionRequest:
    base: dict[str, object] = {
        "ref": SourceRef(
            resolver="huggingface",
            repo="acme/model-GGUF",
            revision="main",
            files=tuple(_shard_name(i) for i in range(1, 5)),
        ),
        "model_id": "acme-model",
        "variant_id": "acme-model-q4",
        "kind": "gguf",
        "quantization": "Q4_K_M",
        "license": "apache-2.0",
    }
    base.update(overrides)
    return AcquisitionRequest(**base)  # type: ignore[arg-type]


async def _acquire(
    store: ModelStore,
    transport: httpx2.MockTransport,
    *,
    token: str | None = None,
    **kwargs: object,
):
    client = _client(transport)
    try:
        return await acquire(
            _request(token=token),
            store=store,
            client=client,
            **kwargs,  # type: ignore[arg-type]
        )
    finally:
        await client.aclose()


# ---- placement and the index ---------------------------------------------------------


def test_placement_is_revision_scoped_so_two_revisions_coexist() -> None:
    ref = SourceRef(repo="acme/Model-GGUF")
    first = placement_for("gguf", ref, revision="a" * 40, variant_id="v")
    second = placement_for("gguf", ref, revision="b" * 40, variant_id="v")
    assert first != second
    assert first.startswith("gguf/acme/model-gguf/")


def test_the_index_round_trips(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    entry = StoreEntry(
        id="e1",
        model_id="m",
        variant_id="v",
        directory="gguf/a/b/c",
        handle="gguf/a/b/c/model.gguf",
        files=(StoredFile(path="model.gguf", size_bytes=10, digest="d", verified=True),),
    )
    store.register(entry)
    reloaded = ModelStore(tmp_path).get("e1")
    assert reloaded is not None
    assert reloaded.handle == entry.handle
    assert reloaded.installed_at > 0


def test_a_corrupt_index_reads_as_empty_rather_than_raising(tmp_path: Path) -> None:
    """The files are still there; refusing to work because a cache file truncated is worse."""
    store = ModelStore(tmp_path)
    store.index_path.parent.mkdir(parents=True, exist_ok=True)
    store.index_path.write_text("{not json", encoding="utf-8")
    assert store.list_installed() == []


def test_rebuild_index_drops_entries_whose_files_a_user_deleted(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    directory = tmp_path / "gguf/a/b/c"
    directory.mkdir(parents=True)
    (directory / "model.gguf").write_bytes(b"x" * 10)
    store.register(
        StoreEntry(
            id="present",
            directory="gguf/a/b/c",
            handle="gguf/a/b/c/model.gguf",
            files=(StoredFile(path="model.gguf", size_bytes=10),),
        )
    )
    store.register(
        StoreEntry(
            id="ghost",
            directory="gguf/x/y/z",
            handle="gguf/x/y/z/model.gguf",
            files=(StoredFile(path="model.gguf", size_bytes=10),),
        )
    )
    surviving = store.rebuild_index()
    assert [e.id for e in surviving] == ["present"]


def test_locate_rejects_a_file_whose_size_no_longer_matches(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    directory = tmp_path / "gguf/a/b/c"
    directory.mkdir(parents=True)
    target = directory / "model.gguf"
    target.write_bytes(b"x" * 10)
    store.register(
        StoreEntry(
            id="e",
            model_id="m",
            directory="gguf/a/b/c",
            handle="gguf/a/b/c/model.gguf",
            files=(
                StoredFile(
                    path="model.gguf",
                    size_bytes=10,
                    mtime=target.stat().st_mtime,
                    digest=_digest(b"x" * 10),
                    digest_kind="sha256",
                    verified=True,
                ),
            ),
        )
    )
    assert store.locate("m") is not None

    target.write_bytes(b"x" * 11)
    assert store.locate("m") is None


def test_removing_an_external_entry_unregisters_without_deleting(tmp_path: Path) -> None:
    external = tmp_path / "someone-elses-cache"
    external.mkdir()
    payload = b"weights"
    (external / "model.safetensors").write_bytes(payload)

    store = ModelStore(tmp_path)
    entry = store.adopt_external(
        external,
        entry_id="ext",
        model_id="m",
        variant_id="v",
        expected={"model.safetensors": _digest(payload)},
    )
    assert entry is not None and entry.external

    report = store.remove("ext")
    assert report.removed and report.external
    assert (external / "model.safetensors").exists()
    assert store.get("ext") is None


def test_adoption_is_refused_when_the_bytes_do_not_match(tmp_path: Path) -> None:
    external = tmp_path / "cache"
    external.mkdir()
    (external / "model.safetensors").write_bytes(b"weights")
    store = ModelStore(tmp_path)
    assert (
        store.adopt_external(
            external,
            entry_id="ext",
            model_id="m",
            variant_id="v",
            expected={"model.safetensors": _digest(b"different")},
        )
        is None
    )


def test_a_legacy_flat_file_is_adopted_rather_than_re_downloaded(tmp_path: Path) -> None:
    from anyinfer.local.artifacts import GgufArtifact, GgufFile

    payload = b"old-download" * 100
    (tmp_path / "model.gguf").write_bytes(payload)
    artifact = GgufArtifact(
        id="legacy-model",
        files=(GgufFile("model.gguf", "https://x/model.gguf", _digest(payload)),),
        license="apache-2.0",
    )

    store = ModelStore(tmp_path)
    adopted = store.adopt_legacy_flat([artifact])
    assert len(adopted) == 1
    located = store.locate("legacy-model")
    assert located is not None
    assert located.path == tmp_path / "model.gguf"
    assert located.verified


def test_a_legacy_file_that_fails_verification_is_not_adopted(tmp_path: Path) -> None:
    from anyinfer.local.artifacts import GgufArtifact, GgufFile

    (tmp_path / "model.gguf").write_bytes(b"truncated")
    artifact = GgufArtifact(
        id="legacy-model",
        files=(GgufFile("model.gguf", "https://x/model.gguf", _digest(b"the-real-bytes")),),
        license="apache-2.0",
    )
    assert ModelStore(tmp_path).adopt_legacy_flat([artifact]) == []


# ---- filename safety -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["../../evil.gguf", "/etc/passwd", "C:\\windows\\system32", "a/../../b", "nul.gguf", "a\x00b"],
)
def test_unsafe_remote_file_names_are_refused(name: str) -> None:
    with pytest.raises(ConfigError):
        safe_relative_path(name)


@pytest.mark.parametrize(
    ("hostile_path", "message"),
    [
        ("../../evil.safetensors", "escapes its directory"),
        ("/etc/passwd.safetensors", "absolute path"),
        ("C:/windows/evil.safetensors", "absolute path"),
    ],
)
def test_a_hostile_tree_entry_is_refused_before_anything_is_written(
    tmp_path: Path, hostile_path: str, message: str
) -> None:
    """File names come from a third-party API, so they are attacker-influenced input."""
    hostile = [
        {
            "type": "file",
            "path": hostile_path,
            "size": 10,
            "lfs": {"oid": _digest(b"x"), "size": 10},
        }
    ]
    store = ModelStore(tmp_path)
    request = _request(ref=SourceRef(resolver="huggingface", repo="acme/model", revision="main"))

    async def run() -> None:
        client = _client(_hf_transport(tree=hostile))
        try:
            await acquire(request, store=store, client=client)
        finally:
            await client.aclose()

    with pytest.raises(ConfigError, match=message):
        asyncio.run(run())
    assert not (tmp_path.parent / "evil.safetensors").exists()
    assert store.list_installed() == []


def test_resolve_within_refuses_to_escape_the_entry_directory(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    entry = StoreEntry(id="e", directory="gguf/a/b/c")
    with pytest.raises(ConfigError):
        store.resolve_within(entry, "../../escape.gguf")


# ---- the Hugging Face resolver ---------------------------------------------------------


def test_a_branch_is_resolved_to_an_immutable_commit_before_anything_is_fetched() -> None:
    async def run() -> None:
        client = _client(_hf_transport())
        try:
            resolved = await HuggingFaceResolver(client=client).resolve(
                SourceRef(repo="acme/model-GGUF", revision="main", files=(_shard_name(1),))
            )
        finally:
            await client.aclose()
        assert resolved.revision == COMMIT
        assert COMMIT in resolved.files[0].url

    asyncio.run(run())


def test_the_token_is_sent_to_the_api_and_dropped_on_the_cdn_hop(tmp_path: Path) -> None:
    seen: list[httpx2.Request] = []
    asyncio.run(_acquire(ModelStore(tmp_path), _hf_transport(seen=seen), token="secret-token"))

    api = [r for r in seen if r.url.host == "huggingface.co"]
    cdn = [r for r in seen if r.url.host == "cdn.invalid"]
    assert api and cdn
    assert all(r.headers.get("authorization") == "Bearer secret-token" for r in api)
    assert all("authorization" not in r.headers for r in cdn)


def test_trusted_redirect_only_survives_a_same_origin_hop() -> None:
    assert trusted_redirect("https://huggingface.co/a", "https://huggingface.co/b")
    assert not trusted_redirect("https://huggingface.co/a", "https://cdn.invalid/b")
    assert not trusted_redirect("https://huggingface.co/a", "http://huggingface.co/b")


def test_a_gated_repository_names_the_actual_remedy() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, json={"error": "gated"})

    async def run() -> None:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        try:
            with pytest.raises(LocalRuntimeError) as excinfo:
                await HuggingFaceResolver(client=client).resolve(
                    SourceRef(repo="meta-llama/Llama-3.1-8B", revision="main")
                )
        finally:
            await client.aclose()
        assert "meta-llama/Llama-3.1-8B" in excinfo.value.hint
        assert "HF_TOKEN" in excinfo.value.hint

    asyncio.run(run())


def test_pickle_weights_are_excluded_from_a_snapshot() -> None:
    tree = [
        {"type": "file", "path": "config.json", "size": 4, "oid": "1" * 40},
        {
            "type": "file",
            "path": "model.safetensors",
            "size": 8,
            "lfs": {"oid": "a" * 64, "size": 8},
        },
        {
            "type": "file",
            "path": "pytorch_model.bin",
            "size": 8,
            "lfs": {"oid": "b" * 64, "size": 8},
        },
    ]

    async def run() -> None:
        client = _client(_hf_transport(tree=tree))
        try:
            resolved = await HuggingFaceResolver(client=client).resolve(
                SourceRef(repo="acme/model", revision="main")
            )
        finally:
            await client.aclose()
        names = {f.path for f in resolved.files}
        assert "model.safetensors" in names
        assert "config.json" in names
        assert "pytorch_model.bin" not in names
        assert any("arbitrary code" in w for w in resolved.warnings)

    asyncio.run(run())


# ---- acquisition ---------------------------------------------------------------------


def test_a_four_shard_acquisition_reports_the_full_total_from_the_first_callback(
    tmp_path: Path,
) -> None:
    events = []
    report = asyncio.run(_acquire(ModelStore(tmp_path), _hf_transport(), progress=events.append))

    assert report.entry is not None
    assert events
    assert events[0].total_bytes == 4 * SHARD_BYTES
    assert not events[0].total_is_estimate

    totals = [e.total_downloaded_bytes for e in events]
    assert totals == sorted(totals), "aggregate progress must never go backwards"
    assert totals[-1] == 4 * SHARD_BYTES
    assert sum(1 for e in events if e.phase == "done") == 1
    assert {e.file_count for e in events} == {4}


def test_a_corrupted_shard_registers_nothing_and_locate_stays_empty(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    with pytest.raises(LocalRuntimeError, match="verification"):
        asyncio.run(_acquire(store, _hf_transport(corrupt=3)))

    assert store.list_installed() == []
    assert store.locate("acme-model") is None


def test_resuming_reports_the_position_it_resumed_from(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    request = _request()
    plan = asyncio.run(_plan(request, store, _hf_transport()))

    # Pre-seed one shard's .part file at 60%, as an interrupted run would leave it.
    staging = store.staging_dir(plan.entry_id)
    staging.mkdir(parents=True, exist_ok=True)
    partial = staging / f"{_shard_name(1)}.part"
    prefix = int(SHARD_BYTES * 0.6)
    partial.write_bytes(_shard(1)[:prefix])

    events = []
    report = asyncio.run(_acquire(store, _hf_transport(), progress=events.append))
    assert report.entry is not None
    assert events[0].total_downloaded_bytes == prefix
    assert events[0].session_bytes == 0
    # The resumed shard contributed only its remainder to this run's transfer.
    assert report.downloaded_bytes == 4 * SHARD_BYTES - prefix


def test_a_second_acquisition_reuses_what_is_already_verified(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    asyncio.run(_acquire(store, _hf_transport()))
    again = asyncio.run(_acquire(store, _hf_transport()))
    assert again.reused
    assert again.downloaded_bytes == 0


def test_a_dry_run_writes_nothing_and_reports_the_exact_size(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    report = asyncio.run(_acquire(store, _hf_transport(), dry_run=True))

    assert report.dry_run
    assert report.entry is None
    assert report.plan.total_bytes == 4 * SHARD_BYTES
    assert store.list_installed() == []
    assert not (tmp_path / "gguf").exists()


def test_cancelling_keeps_partial_transfers_and_registers_nothing(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    report = asyncio.run(_acquire(store, _hf_transport(), cancel_check=cancel))
    assert report.cancelled
    assert store.list_installed() == []
    # Cancelling is not deleting: the .part files survive for the next run.
    staging = store.staging_dir(report.plan.entry_id)
    assert any(staging.rglob("*.part"))


def test_a_raising_progress_sink_is_disabled_but_never_fails_the_download(
    tmp_path: Path,
) -> None:
    def hostile(progress: object) -> None:
        raise RuntimeError("this sink is broken")

    report = asyncio.run(_acquire(ModelStore(tmp_path), _hf_transport(), progress=hostile))
    assert report.entry is not None
    assert any("progress callback raised" in w for w in report.warnings)


def test_an_undigested_file_is_refused_unless_the_caller_opts_in(tmp_path: Path) -> None:
    request = _request(
        ref=SourceRef(
            resolver="url",
            urls=("https://host.invalid/model.gguf",),
        )
    )
    store = ModelStore(tmp_path)
    with pytest.raises(LocalRuntimeError, match="cannot be verified"):
        asyncio.run(plan_acquisition(request, store=store))


def test_a_local_path_is_registered_without_copying(tmp_path: Path) -> None:
    """Weights a user already downloaded by hand are adopted where they lie."""
    source = tmp_path / "hand-downloaded"
    source.mkdir()
    payload = b"already-here" * 100
    (source / "model.gguf").write_bytes(payload)

    store = ModelStore(tmp_path / "store")
    request = _request(
        ref=SourceRef(
            resolver="local",
            path=str(source),
            digests={"model.gguf": _digest(payload)},
        )
    )
    report = asyncio.run(acquire(request, store=store))
    assert report.entry is not None
    assert report.entry.files[0].verified
    assert report.downloaded_bytes == 0


def test_a_local_path_with_reserved_characters_is_registered(tmp_path: Path) -> None:
    """The file:// round trip must survive a directory name that needs escaping.

    Registration hands the resolver's path to acquisition as a ``file://`` URL, so the
    two ends have to agree on the encoding. A space is the cheapest thing that disagrees:
    ``Path.as_uri`` writes it as ``%20``, and any decoder that merely trims the scheme
    hands back a path that does not exist. "My Models" is also what the directory is
    actually called on a real desktop.
    """
    source = tmp_path / "My Models"
    source.mkdir()
    payload = b"escaped-path" * 100
    (source / "model.gguf").write_bytes(payload)

    store = ModelStore(tmp_path / "store")
    request = _request(
        ref=SourceRef(
            resolver="local",
            path=str(source),
            digests={"model.gguf": _digest(payload)},
        )
    )
    report = asyncio.run(acquire(request, store=store))
    assert report.entry is not None
    assert report.entry.files[0].verified
    assert report.downloaded_bytes == 0


def test_progress_callbacks_are_throttled_but_never_miss_a_phase(tmp_path: Path) -> None:
    events = []
    asyncio.run(_acquire(ModelStore(tmp_path), _hf_transport(), progress=events.append))
    phases = {e.phase for e in events}
    assert {"planning", "downloading", "placing", "done"} <= phases
    # A megabyte in 256 KiB shards must not produce hundreds of callbacks.
    assert len(events) < 60


def test_launch_hints_describe_the_engine_without_starting_anything(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    report = asyncio.run(_acquire(store, _hf_transport()))
    assert report.entry is not None

    hints = launch_hints_for(
        report.entry, path=store.root / report.entry.handle, context_size=16384, gpu_layers=99
    )
    assert hints["engine"] == "llama.cpp"
    assert hints["ctx_size"] == 16384
    assert hints["n_gpu_layers"] == 99


def test_the_store_index_records_the_resolved_commit(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    report = asyncio.run(_acquire(store, _hf_transport()))
    assert report.entry is not None
    assert report.entry.source["revision"] == COMMIT
    document = json.loads(store.index_path.read_text(encoding="utf-8"))
    assert document["format_version"] == 1


async def _plan(request, store, transport):
    """Resolve a plan against the fake API."""
    client = _client(transport)
    try:
        return await plan_acquisition(request, store=store, client=client)
    finally:
        await client.aclose()


def test_two_concurrent_acquisitions_transfer_once_and_both_succeed(tmp_path: Path) -> None:
    """The cross-process lock has to make the second caller wait, not duplicate the work."""
    store = ModelStore(tmp_path)

    async def run() -> tuple[object, object]:
        first_client = _client(_hf_transport())
        second_client = _client(_hf_transport())
        try:
            return await asyncio.gather(  # type: ignore[return-value]
                acquire(_request(), store=store, client=first_client),
                acquire(_request(), store=store, client=second_client),
            )
        finally:
            await first_client.aclose()
            await second_client.aclose()

    first, second = asyncio.run(run())
    assert first.entry is not None and second.entry is not None
    assert first.entry.id == second.entry.id
    # One of the two did the work; the other found it already verified.
    transferred = [r for r in (first, second) if r.downloaded_bytes > 0]
    assert len(transferred) == 1
    assert len(store.list_installed()) == 1


def _snapshot_tree() -> list[dict[str, object]]:
    """A vLLM-shaped repository: safetensors, config, tokenizer, and a pickle to skip."""
    files = {
        "config.json": b'{"model_type":"qwen2"}',
        "tokenizer.json": b'{"version":"1.0"}',
        "generation_config.json": b"{}",
        "model-00001-of-00002.safetensors": b"S" * 4096,
        "model-00002-of-00002.safetensors": b"T" * 4096,
        "model.safetensors.index.json": b'{"weight_map":{}}',
        "pytorch_model.bin": b"P" * 4096,
        "README.md": b"# readme",
    }
    return [
        {
            "type": "file",
            "path": name,
            "size": len(body),
            "lfs": {"oid": _digest(body), "size": len(body)},
        }
        for name, body in files.items()
    ]


def _snapshot_transport() -> httpx2.MockTransport:
    bodies = {
        "config.json": b'{"model_type":"qwen2"}',
        "tokenizer.json": b'{"version":"1.0"}',
        "generation_config.json": b"{}",
        "model-00001-of-00002.safetensors": b"S" * 4096,
        "model-00002-of-00002.safetensors": b"T" * 4096,
        "model.safetensors.index.json": b'{"weight_map":{}}',
        "pytorch_model.bin": b"P" * 4096,
        "README.md": b"# readme",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/revision/main"):
            return httpx2.Response(200, json={"sha": COMMIT})
        if "/tree/" in path:
            return httpx2.Response(200, json=_snapshot_tree())
        name = path.rsplit("/", 1)[-1]
        body = bodies[name]
        return httpx2.Response(200, content=body, headers={"content-length": str(len(body))})

    return httpx2.MockTransport(handler)


def test_a_vllm_snapshot_lands_as_a_directory_with_no_pickle_weights(tmp_path: Path) -> None:
    store = ModelStore(tmp_path)
    request = _request(
        ref=SourceRef(resolver="huggingface", repo="acme/model", revision="main"),
        kind="hf_repo",
        engine="vllm",
        quantization="awq",
    )

    async def run() -> object:
        client = _client(_snapshot_transport())
        try:
            return await acquire(request, store=store, client=client)
        finally:
            await client.aclose()

    report = asyncio.run(run())
    assert report.entry is not None

    directory = store.root / report.entry.directory
    assert directory.is_dir()
    names = {p.name for p in directory.rglob("*") if p.is_file()}
    assert "config.json" in names
    assert "tokenizer.json" in names
    assert "model-00001-of-00002.safetensors" in names
    assert "pytorch_model.bin" not in names, "pickle weights execute code on load"
    assert not any(n.endswith(".bin") for n in names)

    located = store.locate("acme-model", engine="vllm")
    assert located is not None
    assert located.path == directory, "a snapshot's handle is the directory itself"

    hints = launch_hints_for(
        report.entry, path=located.path, context_size=32768, gpu_memory_utilization=0.9
    )
    assert hints["engine"] == "vllm"
    assert hints["quantization"] == "awq"
    assert hints["max_model_len"] == 32768
