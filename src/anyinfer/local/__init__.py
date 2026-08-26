"""The local-inference subsystem.

Nine cooperating pieces that turn "run this model locally" into something a novice can do:

- `anyinfer.local.hardware` — what this machine has, advisory and cached.
- `anyinfer.local.backends`, which llama.cpp runtime variants are installed.
- `anyinfer.local.runtimes` — fetching and validating those runtime variants.
- `anyinfer.local.tuning` — hardware + posture → concrete server flags.
- `anyinfer.local.fit` — catalog entry + hardware → will it run, and why.
- `anyinfer.local.variants` — hardware + engine → which quantization to acquire.
- `anyinfer.local.downloads` — pinned, verified, resumable artifact fetches.
- `anyinfer.local.acquire` / `anyinfer.local.store` — getting weights onto this disk and
  finding them again.
- `anyinfer.local.server` — supervised llama-server processes, loopback only.
- `anyinfer.local.recommend` — hardware → catalog tier.
- `anyinfer.local.discovery`, which providers this machine can already use.

Model acquisition lives here, never in a provider adapter: adapters translate protocol, and
fetching forty gigabytes is not protocol translation.
"""

from .acquire import (
    AcquisitionPhase,
    AcquisitionPlan,
    AcquisitionProgress,
    AcquisitionReport,
    ProgressSink,
    acquire,
    acquire_sync,
    plan_acquisition,
)
from .artifacts import GgufArtifact, GgufFile
from .attestation import (
    ATTESTATION_CACHE_BYPASS_ENV,
    ATTESTATION_CACHE_REFRESH_ENV,
    ConfidentialExecutionStatus,
    CpuTeeKind,
    confidential_execution_status,
)
from .attestation import cache_path as attestation_cache_path
from .backends import BACKEND_RANK, Backend, available_backends, select_backend
from .discovery import (
    KEYRING_IDENTIFIER_SUFFIX,
    DiscoveredProvider,
    DiscoveryEvidence,
    discover,
    endpoint_candidates,
)
from .downloads import (
    ALLOWED_LICENSES,
    DownloadReport,
    ProgressCallback,
    artifact_paths,
    default_model_dir,
    download_artifact,
    iter_missing,
    license_allowed,
    verify_file,
)
from .fit import FitLevel, ModelFit, SizedEntry, classify_fit, memory_budget, sort_by_fit
from .hardware import (
    CACHE_BYPASS_ENV,
    CACHE_REFRESH_ENV,
    Accelerator,
    AcceleratorKind,
    HardwareProfile,
    cache_path,
    detect,
    probe_signature,
)
from .metrics import ResourceSample, StorageProfile, SystemSampler, storage_profile
from .provenance import (
    ModelManifest,
    VerifiedWeights,
    WeightsProvenance,
    hash_model_weights,
    open_verified_weights,
    verify_model_manifest,
)
from .recommend import Recommendation, Tier, TierSource, recommend_alias
from .runtimes import (
    InstallReport,
    RuntimeArtifact,
    RuntimeManifest,
    RuntimeTable,
    check_cuda_preconditions,
    default_runtime_kind,
    install_hint,
    install_runtime,
    installed_runtimes,
    load_runtime_table,
    remove_runtime,
    runtime_root,
)
from .server import (
    LOOPBACK_HOST,
    LifecycleCallback,
    ManagedServer,
    ServerHandle,
    ServerSupervisor,
    allocate_port,
    is_loopback,
)
from .sources import RemoteFile, ResolvedArtifact, SourceRef, SourceResolver
from .store import (
    ModelStore,
    PrunePlan,
    PruneProposal,
    RemovalReport,
    ResolvedModel,
    StoreEntry,
)
from .tuning import (
    CONTEXT_LADDER,
    Posture,
    ServerPlan,
    TuningInputs,
    kv_bytes_per_token,
    plan_server,
)
from .variants import VariantChoice, VariantPrefs, evaluate_variants, select_variant

__all__ = [
    "ALLOWED_LICENSES",
    "ATTESTATION_CACHE_BYPASS_ENV",
    "ATTESTATION_CACHE_REFRESH_ENV",
    "BACKEND_RANK",
    "CACHE_BYPASS_ENV",
    "CACHE_REFRESH_ENV",
    "CONTEXT_LADDER",
    "KEYRING_IDENTIFIER_SUFFIX",
    "LOOPBACK_HOST",
    "Accelerator",
    "AcceleratorKind",
    "AcquisitionPhase",
    "AcquisitionPlan",
    "AcquisitionProgress",
    "AcquisitionReport",
    "Backend",
    "ConfidentialExecutionStatus",
    "CpuTeeKind",
    "DiscoveredProvider",
    "DiscoveryEvidence",
    "DownloadReport",
    "FitLevel",
    "GgufArtifact",
    "GgufFile",
    "HardwareProfile",
    "InstallReport",
    "LifecycleCallback",
    "ManagedServer",
    "ModelFit",
    "ModelManifest",
    "ModelStore",
    "Posture",
    "ProgressCallback",
    "ProgressSink",
    "PrunePlan",
    "PruneProposal",
    "Recommendation",
    "RemoteFile",
    "RemovalReport",
    "ResolvedArtifact",
    "ResolvedModel",
    "ResourceSample",
    "RuntimeArtifact",
    "RuntimeManifest",
    "RuntimeTable",
    "ServerHandle",
    "ServerPlan",
    "ServerSupervisor",
    "SizedEntry",
    "SourceRef",
    "SourceResolver",
    "StorageProfile",
    "StoreEntry",
    "SystemSampler",
    "Tier",
    "TierSource",
    "TuningInputs",
    "VariantChoice",
    "VariantPrefs",
    "VerifiedWeights",
    "WeightsProvenance",
    "acquire",
    "acquire_sync",
    "allocate_port",
    "artifact_paths",
    "attestation_cache_path",
    "available_backends",
    "cache_path",
    "check_cuda_preconditions",
    "classify_fit",
    "confidential_execution_status",
    "default_model_dir",
    "default_runtime_kind",
    "detect",
    "discover",
    "download_artifact",
    "endpoint_candidates",
    "evaluate_variants",
    "hash_model_weights",
    "install_hint",
    "install_runtime",
    "installed_runtimes",
    "is_loopback",
    "iter_missing",
    "kv_bytes_per_token",
    "license_allowed",
    "load_runtime_table",
    "memory_budget",
    "open_verified_weights",
    "plan_acquisition",
    "plan_server",
    "probe_signature",
    "recommend_alias",
    "remove_runtime",
    "runtime_root",
    "select_backend",
    "select_variant",
    "sort_by_fit",
    "storage_profile",
    "verify_file",
    "verify_model_manifest",
]
