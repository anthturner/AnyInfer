# Running the sidecar as a managed service

**Scope:** generate (and optionally install) the service definition that keeps
`anyinfer serve` running across logins and reboots — systemd units, launchd agents, and
Windows scheduled tasks — for both the pip install and the standalone bundle. **Goal:**
the "no Python required" delivery path ends at a service that survives a reboot, not at a
terminal window someone has to keep open. **Non-goal:** a supervisor, a process manager,
or any privileged action taken without the user asking for it.

**Audience for this plan:** contributors editing the existing files directly. Code audit
is as of **2026-08-09**; re-verify before starting each task.

**Authority:** DESIGN.md §2 (goal 8, two first-class integration paths; non-goal — "no
daemon in the core"), §22 (serve frontend), ADR-009 (the frontend is a wire codec),
ADR-010 (standalone service binaries via PyInstaller onedir); SECURITY.md.

**Governance intent:** no ADR. This is packaging and operator ergonomics around an
existing, already-decided module. One line of the non-goal needs care in review: "no
daemon **in the core**" stays true — nothing here changes the library, and the service
being installed is the optional `serve` frontend that ADR-009 already sanctions.

---

## 1. Motivation and evidence

The delivery path is finished right up to the last step:

- `anyinfer serve` exists with `--host`, `--port`, `--config`, `--token`,
  `--allow-remote-exposure`, `--expose`
  ([cli.py:38-61](../src/anyinfer/cli.py#L38-L61)).
- Standalone bundles are built natively for five OS/arch pairs and attached to every
  release with SHA-256 checksums
  ([.github/workflows/release.yml:100-130](../.github/workflows/release.yml#L100-L130)),
  via `python workspace.py build serve`.
- The README pitches the sidecar as the integration path for "non-Python applications and
  existing OpenAI clients".

An application pointing at `http://127.0.0.1:8080/v1` needs that endpoint to exist at
boot. Today the answer is "write your own unit file", which means every operator
re-derives the same five decisions — working directory, config path, restart policy,
token handling, and whether to bind loopback — and the security-relevant ones are the
easiest to get wrong. A generated unit is also *documentation that cannot drift*: it
encodes the flags the current version actually accepts.

## 2. Design

### 2.1 Generate by default, install only when asked

```
$ anyinfer serve install --print                 # write the unit to stdout, do nothing
$ anyinfer serve install                         # user scope, current user, no privileges
$ anyinfer serve install --system                # requires elevation; refuses to self-elevate
$ anyinfer serve uninstall
$ anyinfer serve status
```

Rules, in the same spirit as `init`'s:

- **Print before install.** Every install path shows the exact file it will write and the
  exact command it will run, and asks for confirmation unless `--yes`.
- **User scope by default.** `systemd --user`, `~/Library/LaunchAgents`, and a per-user
  scheduled task need no privileges. `--system` prints the elevated command rather than
  attempting to elevate — a library that shells into `sudo` is not something to ship.
- **Never overwrite silently.** An existing unit stops the command with a hint, mirroring
  the config writer's rule.
- **Uninstall is complete.** Whatever install wrote, uninstall removes; `status` reports
  what exists.

### 2.2 Per-platform definitions

| Platform | Artifact | Notes |
|---|---|---|
| Linux | systemd unit (`~/.config/systemd/user/anyinfer-serve.service` or `/etc/systemd/system/`) | Hardening directives on by default: `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `RestrictAddressFamilies` |
| macOS | launchd plist (`~/Library/LaunchAgents/dev.anyinfer.serve.plist`) | `RunAtLoad`, `KeepAlive` with a throttle so a crash loop does not spin |
| Windows | Scheduled Task XML, registered for the current user at logon | Deliberately *not* a Windows Service: the PyInstaller bundle is a console executable with no SCM handshake, and shipping a service shim to fake one would be a second supervisor |

The Windows choice must be stated plainly in the docs rather than papered over. A
scheduled task at logon is honest and needs no privileges; a user who genuinely needs a
boot-time service can be pointed at a third-party wrapper, with the caveat that it is
theirs to maintain.

### 2.3 Executable resolution

The generated definition must name an executable that will still exist:

- pip install → the resolved console script path (`shutil.which("anyinfer")`), with the
  virtualenv's interpreter recorded so a unit does not depend on `PATH`.
- standalone bundle → the absolute path of the running executable
  (`sys.executable` under a frozen build, detected via `sys.frozen`).

If the resolved path lies inside a temp or extraction directory, the command refuses and
explains — a unit pointing into a PyInstaller onefile scratch dir is a unit that breaks on
the next boot. (The bundles are onedir per ADR-010, so this is a guard, not the normal
path.)

### 2.4 Secrets and exposure

- The bearer token is **never** written into the unit body. It goes to a mode-0600
  environment file beside the unit (`ANYINFER_SERVE_TOKEN`), or is referenced from the OS
  keyring via the existing `credential://` scheme when `[keyring]` is installed.
- A generated definition binds loopback unless `--allow-remote-exposure` is passed *and* a
  token is configured — the same guard the running command enforces, applied at generation
  time so a non-loopback unit cannot be produced without one.
- The generated file is echoed with the token elided, and the whole output passes through
  `anyinfer.redaction` before printing.

## 3. Tasks

**SI.1 — definition templates.** New `src/anyinfer/serve/service.py` holding the three
templates and a `ServiceDefinition` dataclass (`path`, `content`, `install_command`,
`uninstall_command`, `scope`). Pure string generation, no side effects — so it is fully
testable on every platform regardless of which one the test runs on. *Acceptance:* new
`tests/test_serve_service.py` renders all three on all three platforms and asserts: the
token never appears in the body; loopback binding unless explicitly exposed; the executable
path is absolute.

**SI.2 — `serve install` / `uninstall` / `status`.** Subcommands under the existing `serve`
parser (`serve` gains a subparser group — check that this does not break `anyinfer serve`
with no subcommand, which must keep running the server). *Acceptance:* `tests/test_cli_serve_service.py`
covers `--print` writing nothing to disk, refusal on an existing unit, and `--system`
printing rather than executing.

**SI.3 — executable resolution + frozen detection.** Per §2.3, including the temp-path
refusal. *Acceptance:* tests for both the console-script and the frozen case (frozen
simulated by patching `sys.frozen`/`sys.executable`).

**SI.4 — token handling.** Env-file writing at 0600 (and the Windows ACL equivalent —
`os.chmod` is close to meaningless there, so use the documented restricted-ACL approach or
decline to write the file and instruct instead). *Acceptance:* a test asserts file mode on
POSIX and that the token is absent from the unit body on every platform.

**SI.5 — bundle integration.** The standalone `anyinfer-serve` bundle ships the same
command; the release archive gains a short `INSTALL.txt` generated from the same templates,
so the download and the CLI never disagree. *Acceptance:* `workspace.py build serve`
produces it; `tests/test_packaging.py` asserts its presence in the built layout.

**SI.6 — docs.** New `docs/serve/running-as-a-service.md` linked from
[docs/serve/README.md](../docs/serve/README.md) and the
[downloads page](../docs/downloads.md). State the Windows scheduled-task decision and its
reason. Cross-link the security guidance on tokens and exposure.

## 4. Testing

`tests/test_serve_service.py` (rendering, platform-independent) and
`tests/test_cli_serve_service.py` (command behaviour, no privileged operations, nothing
written without confirmation). No test may install anything into the developer's real
systemd/launchd/Task Scheduler — every install path is exercised against a temp root
injected as a parameter, which is why §3's `ServiceDefinition` carries its target path as
data rather than computing it inline.

## 5. Risks

- **R-SI1 — a service exposed to the network.** The worst outcome here is an unauthenticated
  sidecar on `0.0.0.0` surviving reboots. Mitigate: generation-time enforcement of the
  token-plus-exposure rule, loopback default, and the hardening directives.
- **R-SI2 — a token on disk.** Unavoidable for an unattended service; mitigate with mode
  0600, keyring referencing, and never embedding it in the unit body or the printed output.
- **R-SI3 — privileged operations from a library CLI.** Mitigate: user scope by default,
  `--system` prints rather than elevates, confirmation before any write.
- **R-SI4 — platform sprawl.** Three definition formats to keep current across OS
  releases. Mitigate: pure-string generation with full test coverage, and no attempt to
  support init systems beyond systemd.

## 6. Decisions (2026-08-09)

1. **`install` runs `anyinfer verify` after starting the service**, unless `--no-verify`.
   A service that starts and then fails every request at 3am because a credential
   reference is wrong is the failure this prevents, and it is the same "prove it works"
   instinct as `init`. The verify result is reported; a failure does not uninstall the
   service, it just says so.
2. **No log redirection by default; `--log-file` opts in, and nothing rotates it.**
   systemd and launchd give journald and `os_log` for free. The Windows scheduled task has
   no sink, so `--log-file` writes one — and the generated definition and the docs both
   state plainly that AnyInfer does not rotate it, because a library that silently grows a
   file on someone's disk forever is worse than one that says it will not manage logs.
3. **`serve status` stays, strictly read-only.** It reports whether the definition exists
   and what the platform's manager says about it. It never starts, stops, or restarts —
   that is the platform manager's job, and the moment this command starts issuing control
   verbs it has become the process supervisor this plan disclaims. Name that boundary in
   the docs page.
