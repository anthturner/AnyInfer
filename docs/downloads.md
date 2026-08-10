---
hide:
  - toc
---

# Download AnyInfer

<span class="anyinfer-badge">v{{ extra.anyinfer_version }}</span>

Every merge to `main` with a version bump produces a
[GitHub Release](https://github.com/anthturner/AnyInfer/releases) carrying the packages
below, built by the
[release workflow](https://github.com/anthturner/AnyInfer/blob/main/.github/workflows/release.yml).

<div class="anyinfer-card-grid" markdown>

<div class="anyinfer-card anyinfer-download-card" markdown>

### :material-language-python: Python wheel

For applications. Published to [PyPI](https://pypi.org/project/anyinfer/); installing
from the repository is byte-identical.

```bash
pip install anyinfer
# or, straight from the repository:
pip install "anyinfer @ git+https://github.com/anthturner/AnyInfer@main"
```

[Latest release :material-arrow-right:](https://github.com/anthturner/AnyInfer/releases/latest)
{ .anyinfer-button .anyinfer-button-secondary }

</div>

<div class="anyinfer-card anyinfer-download-card" markdown>

### :material-monitor-dashboard: Demo app bundle

Self-contained — unzip and run, no Python required. Fully offline, no credentials needed.

:material-microsoft-windows: [Windows (x64)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-windows-x64.zip)
<br>:material-apple: [macOS (Apple silicon)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-macos-arm64.zip) · [macOS (Intel)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-macos-x64.zip)
<br>:material-linux: [Linux (x64)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-linux-x64.zip) · [Linux (arm64)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-linux-arm64.zip)

Or with Python already installed:

```bash
pip install "anyinfer[demo]" && anyinfer-demo
```

</div>

<div class="anyinfer-card anyinfer-download-card" markdown>

### :material-server-network: Sidecar bundle

The OpenAI-compatible service, self-contained for integrations that do not use Python.

:material-microsoft-windows: [Windows (x64)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-windows-x64.zip)
<br>:material-apple: [macOS (Apple silicon)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-macos-arm64.zip) · [macOS (Intel)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-macos-x64.zip)
<br>:material-linux: [Linux (x64)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-linux-x64.zip) · [Linux (arm64)](https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-linux-arm64.zip)

Or with Python already installed:

```bash
pip install "anyinfer[serve]"
anyinfer serve --config anyinfer.json
```

[Sidecar documentation :material-arrow-right:](serve/README.md)
{ .anyinfer-button .anyinfer-button-secondary }

</div>

</div>

## Installation

```bash
pip install anyinfer
```

The core depends on only `httpx2` and `jsonschema`; everything else is an extra. See
[installation and extras](guides/installation.md) for which extras you need.

## Notes

- Unzip the demo bundle, then run the `anyinfer-demo` executable inside. The bundled
  `BUNDLE-INFO.txt` records the exact version. Bundles never embed `llama-server` binaries
  or model weights — install a runtime explicitly and let the local subsystem acquire
  verified model artifacts when needed.
- Unzip the sidecar bundle and run `anyinfer-serve --config anyinfer.json` from inside it.
  To keep it running across reboots, `anyinfer-serve install` writes the service
  definition for your platform after showing it to you; the archive's `INSTALL.txt`
  carries the same text. See
  [running as a service](serve/running-as-a-service.md).
  It includes the HTTP frontend and built-in dependency-free adapters. Integrations that
  require an optional provider SDK, such as GitHub Copilot or Entra authentication, should
  install the Python distribution with the corresponding extra.
- On 32-bit Windows (x86) there is no standalone demo bundle — PySide6 publishes no
  32-bit Qt builds — but the library wheel itself is pure Python and runs there fine.

## Previous releases and checksums

The [releases page](https://github.com/anthturner/AnyInfer/releases) keeps every prior
version with its changelog, generated from the pull requests that landed between
releases, plus the checksums for every attached asset. The versioning and branch policy
is documented in the [release strategy](contributing/releasing.md).
