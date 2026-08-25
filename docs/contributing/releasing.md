# Branching and releases

How changes travel from a feature branch to a published release, and what is mechanical
versus what a maintainer decides.

## The branch model

```mermaid
flowchart LR
  A["feature/&lt;topic&gt;"] -->|PR| B[develop]
  B -->|PR| C[main]
  C --> D[release packages]
```

- **`feature/*`**: all work happens here, one topic per branch. Branched from `develop`.
- **`develop`**: the integration branch. Feature branches merge in by pull request;
  [CI](https://github.com/anthturner/AnyInfer/blob/main/.github/workflows/ci.yml) must be
  green before the merge button works.
- **`main`**: always releasable. Receives only pull requests from `develop`, again
  gated on CI. Every merge to `main` rebuilds the release packages; a merge that bumps
  the version also publishes them.

Both protected branches require the aggregate `ci-ok` status check, which passes only
when every lint, type, contract, conformance, docs, and bracketed test-matrix job passed.
Requiring one stable check name means adding a CI job (or a matrix row) can never silently
escape the protection rules.

`main` requires three additional checks — `tests (ubuntu-latest, py3.12)`,
`tests (ubuntu-latest, py3.13)`, and `tests (macos-latest, py3.14)`. Those are the
names GitHub *reports*, which is what a required context matches on: a job's `name:`, not
its id. Naming the id (`test-macos`) registers a context no job ever reports, and a
required context that never reports blocks every pull request into the branch forever.
Each is a lane whose cost is not worth paying on every feature-branch PR into `develop`:
macOS runners bill at 10x Linux, and the two middle interpreters are two more full
environment builds to re-prove a suite the 3.11 and 3.14 rows already ran. They run only
on the develop -> main step, right before a merge triggers a release build. The three are
kept out of `ci-ok` and listed as their own required contexts, only on `main`'s
protection rule. A job skipped by `if:` still reports "skipped", and GitHub treats a
skipped required check the same as a failed one, so folding these release-only lanes into
`ci-ok` would block every `develop` pull request.

CI itself is triggered by pull requests into either protected branch, and by pushes to
`main`. Pushes to `develop` do not trigger it: `develop` only takes merges through a pull
request that already had to be green, so re-running the full matrix on the merged commit
bills a second time for a result CI already produced.

## Versioning

- The single source of truth is `project.version` in
  [`pyproject.toml`](https://github.com/anthturner/AnyInfer/blob/main/pyproject.toml);
  `anyinfer.__version__` mirrors it and a test keeps them in agreement.
- Pre-1.0, versions follow `0.MINOR.PATCH`: breaking changes bump MINOR, everything else
  bumps PATCH. From 1.0.0 on, plain [SemVer](https://semver.org/).
- Bumping the version is an ordinary change: edit both files on a feature branch and let
  it ride to `main` through `develop`.

## What a release is

The [release workflow](https://github.com/anthturner/AnyInfer/blob/main/.github/workflows/release.yml)
runs on every merge to `main`:

1. It reads `project.version` and checks whether tag `v<version>` already exists.
2. It rebuilds the release artifacts, so `main` is continuously proven releasable:
    - **the library**: sdist + wheel, `twine check`-ed and smoke-installed, on every merge;
    - **the demo bundles**: standalone PyInstaller builds of the pack-in demo app on
      native runners for Windows (x64), macOS (arm64 and x64), and Linux (x64 and
      arm64), named without a version
      (`anyinfer-demo-<os>-<arch>.zip`) so the site's
      [downloads page](../downloads.md) can link `releases/latest/download/` URLs that
      never go stale;
    - **the sidecar bundles**: native builds on the same runners, named
      `anyinfer-serve-<os>-<arch>.zip`, with a build-time `--help` smoke test.

    Since freezing a PySide6 application on five runners (two of them macOS, at 10x Linux
    billing) is the most expensive thing this repository asks CI to do, the bundle matrix
    depends on the version: a version bump builds all five, and an unchanged version
    builds only the Linux x64 canary that catches a change breaking the frozen build at
    all. Platform-specific freeze breakage therefore surfaces at the version bump rather
    than at the merge before it; no release can be cut without all five going green.
3. **Only when the version is new** does it tag `v<version>` and create the GitHub
   Release, with notes generated from the merged pull requests, every package attached,
   and a `SHA256SUMS` file covering every artifact. An unchanged version (docs-only merges,
   CI tweaks) leaves what it built as workflow artifacts and cuts nothing — releases stay
   1:1 with versions.

Publishing a release therefore takes exactly one deliberate act: merging a version bump
to `main`. There is no separate tagging step to forget or get wrong, and a release's tag
always points at the exact commit it was built from.

The docs site redeploys on every merge to `main` and again when a release publishes, so
the site and the newest release never disagree for long.

## PyPI

The release workflow's `publish-pypi` job uploads the library distribution to
[PyPI](https://pypi.org/project/anyinfer/) on the same condition that cuts a GitHub
Release: a new version on `main`. It downloads the `library-dist` artifact rather than
rebuilding, so what lands on the index is byte-for-byte what `twine check` passed, what
the smoke test installed, and what is attached to the release — one build, three
destinations.

Uploads authenticate by Trusted Publishing (OIDC): PyPI mints a short-lived credential
for a workflow run whose repository, workflow file, and environment match the project's
publisher configuration. No API token exists in this repo's secrets, so there is none to
leak or rotate.

Because publishing is irreversible — a version number on PyPI can be yanked but never
reused — the job runs in the `pypi` environment, which is where a required-reviewer gate
belongs if you want a human to approve each upload. The version bump is still the single
deliberate act; the environment just adds a pause before the copy leaves the building.

## Checklist for cutting a release

1. `develop` is green and contains everything the release should.
2. On a feature branch: bump `project.version` and `anyinfer.__version__`, note anything
   user-facing in the PR description (it becomes the generated release notes).
3. PR into `develop`; merge when green. PR `develop` into `main`; merge when green.
4. Watch the release workflow attach `v<version>` and publish the wheel to PyPI.
5. Verify the [downloads page](../downloads.md), checksum file, and PyPI project page.

If a step fails, [when a release goes wrong](#when-a-release-goes-wrong) lists the
recovery for each failure mode.

Native beta bundles are not code-signed. macOS Gatekeeper and Windows SmartScreen may
therefore require an explicit local approval. Signing and notarization require external
certificates and are a release-infrastructure follow-up; the wheel, source distribution,
checksums, and reproducible workflow remain the authoritative 0.1 release path.

## When a release goes wrong

Publishing is the only irreversible step in this repository: a version number on PyPI can
be yanked but never reused, not even after deleting the file. Recovery by failure mode:

| Symptom | What happened | What to do |
|---|---|---|
| Release cut, `publish-pypi` failed | The publisher fields or the `pypi` environment do not match the run | Fix the registration on PyPI, then re-run the failed job from the Actions run page. |
| Upload rejected: file already exists | That version was uploaded before | Nothing to recover. Bump to the next patch version and let it ride to `main` again. |
| A published version is broken | It is on the index and installable | Yank it (**Manage → Releases → Yank**): resolvers stop selecting it while existing pins keep working. Then release a fix. Deleting instead burns the number permanently. |
| Release cut from the wrong commit | The tag points somewhere unintended | Delete the GitHub Release *and* its tag, fix `main`, and bump the version; reusing the tag would disagree with whatever PyPI already accepted. |
| Run stuck before uploading | The `pypi` environment is waiting on a required reviewer | Approve the deployment on the run page. A run left pending is failed automatically after 30 days. |

Re-running `publish-pypi` never rebuilds: it downloads the same `library-dist` artifact the
build job produced, so a retry cannot ship different bytes than the ones already attached
to the GitHub Release. That artifact is subject to the repository's normal artifact
retention (90 days by default); after it expires, re-run the whole workflow rather than
the single job.
