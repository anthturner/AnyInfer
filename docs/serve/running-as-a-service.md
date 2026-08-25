# Running the sidecar as a service

An application pointing at `http://127.0.0.1:8080/v1` needs that endpoint to exist at boot,
not just while somebody keeps a terminal window open. `anyinfer serve install` writes the
systemd unit, launchd agent, or scheduled task that arranges it, and shows you the file
first. The service runs from the same
[shared configuration file](../reference/configuration.md) as the CLI and SDK.

```bash
anyinfer serve install --print --config anyinfer.json   # see it, write nothing
anyinfer serve install --config anyinfer.json           # write it and register it
anyinfer serve status                                   # read-only
anyinfer serve uninstall
```

The standalone download works the same way: `anyinfer-serve install`. Its archive also
ships an `INSTALL.txt` rendered from the same templates, so the download and the command
cannot describe different definitions.

## What it will and will not do

- **It prints before it writes.** Every path shows the exact file and the exact commands,
  and asks for confirmation unless you pass `--yes`.
- **User scope by default.** `systemctl --user`, a LaunchAgent, and a per-user scheduled
  task all install without privileges. `--system` generates the system-wide definition and
  *prints* the commands to run as root; it will not elevate for you.
- **It never overwrites silently.** An existing definition stops the command; `--force`
  replaces it.
- **`uninstall` removes what `install` wrote**: the definition and, where one exists, the
  private environment file.
- **`status` is read-only.** It reports whether a definition exists and what the platform's
  manager says about it. It never starts, stops, or restarts anything: that is the
  manager's job, and a command that issued control verbs would have become the process
  supervisor AnyInfer is not.

After a successful install the command runs
[`anyinfer verify`](../guides/cli.md) against the configured route, unless you pass
`--no-verify`. A service that starts cleanly and then fails every request at 3am because a
credential reference is wrong is the failure this catches. A failure is reported; nothing
is uninstalled.

## What gets generated

=== "Linux (systemd)"

    `~/.config/systemd/user/anyinfer-serve.service`, or `/etc/systemd/system/` with
    `--system`.

    ```ini
    [Service]
    Type=simple
    ExecStart=/usr/local/bin/anyinfer serve --host 127.0.0.1 --port 8080 --config /srv/anyinfer.json
    EnvironmentFile=-/home/you/.config/anyinfer/serve.env
    Restart=on-failure
    NoNewPrivileges=true
    PrivateTmp=true
    ProtectSystem=strict
    ProtectHome=read-only
    RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
    ```

    The hardening directives are on rather than offered. This process reads a
    configuration file and speaks HTTP; it has no business writing to the filesystem,
    gaining privileges, or opening anything but IP sockets, and a default you have to
    turn on is a default nobody has. Logs go to the journal:
    `journalctl --user -u anyinfer-serve.service`.

=== "macOS (launchd)"

    `~/Library/LaunchAgents/dev.anyinfer.serve.plist`, with `RunAtLoad`, `KeepAlive`, and
    a ten-second `ThrottleInterval` so a crash loop does not spin.

    When a bearer token is configured the agent runs through `/bin/sh` to source the
    private environment file. launchd has no `EnvironmentFile`, and its
    `EnvironmentVariables` dictionary lives in the plist itself, which is exactly where a
    token must not go.

=== "Windows (scheduled task)"

    `%LOCALAPPDATA%\AnyInfer\anyinfer-serve.xml`, registered with `schtasks` to run at
    logon.

    A logon task, not a Windows Service: the sidecar is a console executable, and a
    service shim would be a second supervisor. For boot-time start, use a third-party
    service wrapper; that wrapper is then yours to maintain.

## Tokens and exposure

A loopback service needs no token. Everything below applies only when you expose one.

- **The token never enters the definition.** On Linux and macOS it goes to a mode-0600
  environment file beside the unit, read as `ANYINFER_SERVE_TOKEN`. The file is created at
  that mode rather than tightened afterwards.
- **On Windows no token file is written at all.** A POSIX file mode means little there, so
  the command tells you to set the variable where the OS already guards it:
  `setx ANYINFER_SERVE_TOKEN <token>`. The task inherits it at logon.
- **A non-loopback definition cannot be generated without both** `--allow-remote-exposure`
  and a token. The running server enforces that already; generation enforces it too, so a
  unit that would survive reboots as an unauthenticated gateway cannot be produced at all.
  See the [security guidance](README.md#security) for what exposure means.
- Printed output passes through redaction, so a token cannot reach your terminal or your
  scrollback.

## Logs

Nothing is redirected by default: systemd has the journal and launchd has `os_log`, and
duplicating them into a file helps nobody. The Windows task has no sink, so `--log-file`
writes one, and AnyInfer does not rotate it. The generated definition states that, and so
does this page, so the file's growth never comes as a surprise.

## When the executable moves

The generated definition names an absolute path — the console script, or the standalone
executable under a frozen build. If the path lies inside a temporary or extraction
directory the command refuses and explains: once that directory is cleaned up, the service
fails at the next boot. Unpack the download somewhere permanent and rerun.

After upgrading or relocating, regenerate: `anyinfer serve install --force`.

!!! tip "Key takeaways"
    - `anyinfer serve install` shows the exact definition before writing it, installs at
      user scope by default, and runs `anyinfer verify` against the configured route
      afterwards.
    - `status` reports and never controls; starting and stopping belong to the platform's
      service manager.
    - Exposure rules survive into the definition: no non-loopback unit can be generated
      without both `--allow-remote-exposure` and a bearer token, and the token lives in a
      mode-0600 environment file (or the OS environment on Windows), never in the
      definition itself.
    - Regenerate with `--force` after the executable moves or is upgraded.
