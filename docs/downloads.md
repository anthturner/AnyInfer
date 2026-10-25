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

<div class="anyinfer-card-grid anyinfer-download-grid" markdown>

<div class="anyinfer-card anyinfer-download-card" markdown>

<div class="anyinfer-download-layout" markdown>

<div class="anyinfer-download-intro" markdown>

### :material-language-python: Python Wheel

For applications. Published to [PyPI](https://pypi.org/project/anyinfer/); installing
from the repository is byte-identical.

</div>

<div class="anyinfer-download-install" markdown>

```bash
pip install anyinfer
# or, straight from the repository:
pip install "anyinfer @ git+https://github.com/anthturner/AnyInfer@main"
```

[Latest release :material-arrow-right:](https://github.com/anthturner/AnyInfer/releases/latest)
{ .anyinfer-button .anyinfer-button-secondary }

</div>

</div>

</div>

<div class="anyinfer-card anyinfer-download-card" markdown>

<div class="anyinfer-download-layout" markdown>

<div class="anyinfer-download-intro" markdown>

### :material-monitor-dashboard: Demo App Bundle

Self-contained: unzip and run, no Python required. Fully offline, no credentials needed.

</div>

<div class="anyinfer-download-install" markdown>

<ul class="anyinfer-platforms">
<li>:material-microsoft-windows: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-windows-x64.zip">Windows (x64)</a></li>
<li>:material-apple: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-macos-arm64.zip">macOS (Apple silicon)</a></li>
<li>:material-apple: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-macos-x64.zip">macOS (Intel)</a></li>
<li>:material-linux: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-linux-x64.zip">Linux (x64)</a></li>
<li>:material-linux: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-demo-linux-arm64.zip">Linux (arm64)</a></li>
</ul>

Or with Python already installed:

```bash
pip install "anyinfer[demo]" && anyinfer-demo
```

</div>

</div>

</div>

<div class="anyinfer-card anyinfer-download-card" markdown>

<div class="anyinfer-download-layout" markdown>

<div class="anyinfer-download-intro" markdown>

### :material-server-network: Sidecar Bundle

The OpenAI-compatible service, self-contained for integrations that do not use Python.

</div>

<div class="anyinfer-download-install" markdown>

<ul class="anyinfer-platforms">
<li>:material-microsoft-windows: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-windows-x64.zip">Windows (x64)</a></li>
<li>:material-apple: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-macos-arm64.zip">macOS (Apple silicon)</a></li>
<li>:material-apple: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-macos-x64.zip">macOS (Intel)</a></li>
<li>:material-linux: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-linux-x64.zip">Linux (x64)</a></li>
<li>:material-linux: <a href="https://github.com/anthturner/AnyInfer/releases/latest/download/anyinfer-serve-linux-arm64.zip">Linux (arm64)</a></li>
</ul>

Or with Python already installed:

```bash
pip install "anyinfer[serve]"
anyinfer serve --config anyinfer.json
```

[Sidecar documentation :material-arrow-right:](serve/README.md)
{ .anyinfer-button .anyinfer-button-secondary }

</div>

</div>

</div>

</div>

## Notes

- The Python core wheel depends on only `httpx2` and `jsonschema`; everything else is an extra.
  [Installation and extras](guides/installation.md) lists which ones you need.
- The native .NET 8 C# SDK is not a release artifact or public NuGet package. It is an
  independent prerelease packaged locally as `0.1.0-proof`, with no runtime Python
  dependency. Build it from the checkout using the
  [C# application setup](guides/csharp-sdk.md#use-in-a-net-application); see the
  [C# reference](reference/csharp-sdk.md) and
  [migration map](guides/python-to-csharp.md) for its bounded capability surface.
- Unzip the demo bundle and run the `anyinfer-demo` executable inside; `BUNDLE-INFO.txt`
  records the exact version. Bundles never embed `llama-server` binaries or model
  weights; install a runtime explicitly and let the local subsystem acquire verified
  model artifacts when needed. (No 32-bit Windows bundle: PySide6 publishes no 32-bit Qt
  builds, though the pure-Python wheel runs there fine.)
- Unzip the sidecar bundle and run `anyinfer-serve --config anyinfer.json` from inside
  it. To keep it running across reboots, `anyinfer-serve install` writes the service
  definition for your platform after showing it to you (the archive's `INSTALL.txt`
  carries the same text); see [running as a service](serve/running-as-a-service.md). The
  bundle covers the HTTP frontend and the dependency-free adapters; integrations that
  need an optional provider SDK, such as GitHub Copilot or Entra authentication, should
  install the Python distribution with the corresponding extra.

## Previous Releases and Checksums

The [releases page](https://github.com/anthturner/AnyInfer/releases) keeps every prior
version with its changelog, generated from the pull requests that landed between
releases, plus the checksums for every attached asset. The versioning and branch policy
is documented in the [release strategy](contributing/releasing.md).
