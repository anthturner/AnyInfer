# Local inference

The `anyinfer.local` subsystem: hardware detection, backend selection, runtime
acquisition, tuning, fit classification, model acquisition and storage, server supervision,
and hardware→tier recommendation. Concepts:
[the local subsystem](../../concepts/local.md) ·
[the model catalog](../../concepts/catalog.md) ·
[acquiring models](../../concepts/models.md) · guides:
[run a model locally](../../guides/local-inference.md) ·
[choose and download a local model](../../guides/local-models.md).

```python
from anyinfer import local
```

## Hardware

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.detect

::: anyinfer.local.HardwareProfile

::: anyinfer.local.Accelerator

::: anyinfer.local.AcceleratorKind

::: anyinfer.local.probe_signature

::: anyinfer.local.cache_path

::: anyinfer.local.CACHE_BYPASS_ENV

::: anyinfer.local.CACHE_REFRESH_ENV

</div>

## Resource sampling and storage

Lightweight host metrics used by benchmarks and local-capacity reporting.

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.ResourceSample

::: anyinfer.local.SystemSampler

::: anyinfer.local.StorageProfile

::: anyinfer.local.storage_profile

</div>

## Backends

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.available_backends

::: anyinfer.local.select_backend

::: anyinfer.local.Backend

::: anyinfer.local.BACKEND_RANK

</div>

## Runtime variants

AnyInfer ships no llama.cpp binaries. These fetch, validate, and select them; CUDA is an
explicit opt-in, never installed on a user's behalf.

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.install_runtime

::: anyinfer.local.installed_runtimes

::: anyinfer.local.remove_runtime

::: anyinfer.local.default_runtime_kind

::: anyinfer.local.check_cuda_preconditions

::: anyinfer.local.install_hint

::: anyinfer.local.load_runtime_table

::: anyinfer.local.runtime_root

::: anyinfer.local.RuntimeTable

::: anyinfer.local.RuntimeArtifact

::: anyinfer.local.RuntimeManifest

::: anyinfer.local.InstallReport

</div>

## Tuning

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.plan_server

::: anyinfer.local.TuningInputs

::: anyinfer.local.ServerPlan

::: anyinfer.local.Posture

::: anyinfer.local.CONTEXT_LADDER

::: anyinfer.local.kv_bytes_per_token

</div>

## Fit and variant selection

Whether a model will run on this machine, and which quantization to acquire for it. Both
are advisory and both explain themselves.

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.classify_fit

::: anyinfer.local.ModelFit

::: anyinfer.local.FitLevel

::: anyinfer.local.memory_budget

::: anyinfer.local.sort_by_fit

::: anyinfer.local.SizedEntry

::: anyinfer.local.select_variant

::: anyinfer.local.evaluate_variants

::: anyinfer.local.VariantChoice

::: anyinfer.local.VariantPrefs

</div>

## Acquisition and the model store

Getting weights onto this disk and finding them again. Model acquisition lives here, never
in a provider adapter.

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.acquire

::: anyinfer.local.acquire_sync

::: anyinfer.local.plan_acquisition

::: anyinfer.local.AcquisitionPlan

::: anyinfer.local.AcquisitionProgress

::: anyinfer.local.AcquisitionReport

::: anyinfer.local.AcquisitionPhase

::: anyinfer.local.ProgressSink

::: anyinfer.local.ModelStore

::: anyinfer.local.StoreEntry

::: anyinfer.local.ResolvedModel

::: anyinfer.local.RemovalReport

</div>

## Sources

Where weights come from. Adding an internal mirror is a resolver, not a dependency.

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.SourceRef

::: anyinfer.local.SourceResolver

::: anyinfer.local.ResolvedArtifact

::: anyinfer.local.RemoteFile

</div>

## Artifacts and downloads

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.GgufArtifact

::: anyinfer.local.GgufFile

::: anyinfer.local.download_artifact

::: anyinfer.local.iter_missing

::: anyinfer.local.verify_file

::: anyinfer.local.artifact_paths

::: anyinfer.local.default_model_dir

::: anyinfer.local.DownloadReport

::: anyinfer.local.ProgressCallback

::: anyinfer.local.ALLOWED_LICENSES

::: anyinfer.local.license_allowed

</div>

## Server supervision

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.ServerSupervisor

::: anyinfer.local.ManagedServer

::: anyinfer.local.ServerHandle

::: anyinfer.local.LifecycleCallback

::: anyinfer.local.allocate_port

::: anyinfer.local.LOOPBACK_HOST

::: anyinfer.local.is_loopback

</div>

## Recommendation

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.recommend_alias

::: anyinfer.local.Recommendation

::: anyinfer.local.Tier

::: anyinfer.local.TierSource

</div>

## Discovery

What this machine can already use: engines answering on loopback, and credential
variables that are actually set. This is what `anyinfer init` composes into a
configuration file.

<div class="anyinfer-api-block" markdown>

::: anyinfer.local.discover

::: anyinfer.local.DiscoveredProvider

::: anyinfer.local.DiscoveryEvidence

::: anyinfer.local.endpoint_candidates

::: anyinfer.local.KEYRING_IDENTIFIER_SUFFIX

</div>

## Engine-managed models

<div class="anyinfer-api-block" markdown>

::: anyinfer.PullRequest

::: anyinfer.PullReport

</div>
