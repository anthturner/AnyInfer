# Security policy

## Supported versions

AnyInfer is pre-1.0. Security fixes are applied to the latest published `0.x` release and to
the `main` branch; older pre-1.0 releases are not maintained in parallel.

## Report a vulnerability

Do not open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/anthturner/AnyInfer/security/advisories/new).
If that form is unavailable, email `github@anthturner.com` with the subject
`AnyInfer security report`.

`github.com/anthturner/AnyInfer` is the canonical repository, and
[anyinfer.dev](https://anyinfer.dev/) is the documentation site published from it. Two
names, one project — the repository is where code, releases, and this reporting channel
live. There is no other official reporting address; if you found one elsewhere, it is not
ours.

Include the affected version, integration path, reproduction steps or a proof of concept,
and the impact you expect. Remove API keys, tokens, prompts, model output, and other private
payloads before sending logs or configuration files.

The maintainer will coordinate validation, a fix, and disclosure with the reporter. Please
allow time for a patched release before publishing details that would put users at risk.
