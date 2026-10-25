# Contributing to AnyInfer

The canonical contributor guide is
[`docs/contributing/README.md`](docs/contributing/README.md). It covers environment setup,
the task runner, quality gates, architecture boundaries, workstream ownership, provider
contracts, and the pull-request process.

Start with:

```bash
python -m venv .venv && . .venv/bin/activate     # or .venv\Scripts\activate
python workspace.py setup
python workspace.py check
```

The full `check` also builds the documentation site and the native C# SDK, so it needs Node 24
with `npm --prefix website ci`, the locked documentation requirements in
`website/requirements.lock`, and the .NET SDK selected by `src/csharp/global.json` with
`dotnet tool restore` run from `src/csharp/`. The contributor guide's setup block lists every
command.

Before changing an adapter, read its snapshot under [`contracts/`](contracts/README.md) and
follow the [provider drift procedure](contracts/DRIFT-CHECK.md). Wire changes, snapshot
updates, conformance coverage, and provider documentation belong in the same pull request.

Please report vulnerabilities privately through the [security policy](SECURITY.md), not in
a public issue.
