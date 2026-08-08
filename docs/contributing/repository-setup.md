# Repository setup

The one-time GitHub configuration this repo depends on. Everything here is
*infrastructure state that lives outside the code* — settings and secrets that a fork,
a migration, or a new maintainer must recreate by hand, because no workflow can create
them for itself. Each item below names the workflow that breaks without it; the last
section covers what to do when one of them is wrong and a release has already started.

## Before the first push to `main`

The first commit already declares version `0.1.0`, so its first push to `main` is a real
release: `release.yml` will create `v0.1.0` and attempt the PyPI upload. Do these in
order, and only then push:

1. **Confirm the name is free on PyPI.** Open <https://pypi.org/project/anyinfer/>; a 404
   means it is available. If it is taken, both `project.name` in `pyproject.toml` and the
   publisher registration below have to change — a project cannot be renamed on the index
   after its first upload.
2. **Create the empty GitHub repository** at `anthturner/AnyInfer`. The distribution name
   on PyPI stays lowercase `anyinfer` — that is the normalized package name, and it is
   independent of how the repository is spelled.
3. **Create the `pypi` environment and register the pending PyPI publisher**, both under
   [PyPI trusted publishing](#pypi-trusted-publishing). PyPI matches on the environment
   name, so the environment has to exist before the first release run — this is the step
   that cannot be done afterwards without a failed release in the history.
4. **Push `main`.** The release workflow tags `v0.1.0`, cuts the GitHub Release, and
   uploads to PyPI.
5. **Create `develop` from `main`** and protect both branches
   ([commands](releasing.md#one-time-repository-setup)).

Pages and branch protection can be configured after the first push, once the branches and
the `ci-ok` check exist. Do not push an unreleased version to `main` merely to bootstrap
repository settings.

## Branch protection

`develop` and `main` are protected and gated on the aggregate **`ci-ok`** status check —
one stable name, so the required check never has to enumerate matrix jobs. The exact
one-time `gh` commands live in [branching and releases](releasing.md).

`develop` is load-bearing infrastructure, not a convention: `ci.yml` triggers on pull
requests into it, and both refresh workflows open their pull requests **against
`develop`**. A scheduled refresh that fires before the branch exists fails at PR creation.

Breaks without it: nothing *fails*, which is the problem — merges land without the gates.

## GitHub Pages

**Settings → Pages → Source: "GitHub Actions".** The docs site deploys from
`pages.yml` on every merge to `main` and on every published release; the workflow
carries the `pages: write` / `id-token: write` permissions it needs, but the source
selection cannot be set by a workflow.

Breaks without it: `pages.yml` deploy jobs fail; the site never publishes.

## Actions settings

**Settings → Actions → General → Workflow permissions → tick "Allow GitHub Actions to
create and approve pull requests".** Both refresh workflows' proposal stages open a pull
request with their verified changes; without this toggle the PR creation is rejected at
the API level even though each workflow's own `permissions:` block requests
`pull-requests: write`.

Also set **Fork pull request workflows from outside collaborators** to *Require approval
for all outside collaborators* — the reasoning is in
[branching and releases](releasing.md#one-time-repository-setup).

Two facts about scheduled workflows worth knowing up front:

- The weekly crons in `pricing-refresh.yml` (Mondays 06:00 UTC) and `catalog-refresh.yml`
  (06:30 UTC) only fire from the **default branch** — the workflow files must exist on
  `main` before the schedules are live.
- GitHub suspends cron schedules in repositories with no activity for ~60 days; the
  Actions tab shows a re-enable banner when that happens.

## Secrets

Configured under **Settings → Secrets and variables → Actions**. `GITHUB_TOKEN` is
provided automatically and is not listed.

| Secret | Used by | Required | What it is |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `pricing-refresh.yml`, `catalog-refresh.yml` (propose stages) | One of these two | An Anthropic **Console** API key ([platform.claude.com](https://platform.claude.com) → API keys). Billed per token against the Console account's credits. |
| `CLAUDE_CODE_OAUTH_TOKEN` | `pricing-refresh.yml`, `catalog-refresh.yml` (propose stages) | One of these two | A Claude Code OAuth token minted from a **Claude Pro/Max subscription** by running `claude setup-token` on your machine. Draws on the subscription's usage limits instead of per-token billing. |

Set exactly one. Which one is right:

- **A claude.ai account is not an API account.** A claude.ai subscription (Free, Pro,
  Max) and an Anthropic Console account are separate things with separate billing —
  the same split as ChatGPT vs the OpenAI API. Having Pro does not give you an API key,
  and buying API credits does not give you claude.ai access.
- **But unlike the OpenAI split, the subscription *can* drive this workflow.** Claude
  Code authenticates against Pro/Max subscriptions, and `claude-code-action` accepts
  that as `claude_code_oauth_token` — run `claude setup-token` locally, paste the
  result into the secret, and the weekly refresh runs on your subscription.
- **Trade-offs.** The API key is the service-account-shaped option: org-owned, no
  expiry surprises, costs pennies per run at this workflow's size. The OAuth token is
  tied to a personal subscription, shares its usage limits with your interactive use,
  and may need re-minting when the token is revoked or expires — fine for a personal
  repo, wrong for an org one.

Without either secret, the deterministic drift checks still run weekly and the workflow
summaries still surface drift; only the automated verify-and-open-a-PR stages fail
(visibly, in the Actions log).

No other workflow needs a secret: `ci.yml`, `release.yml`, and `pages.yml` run entirely
on the automatic `GITHUB_TOKEN`. PyPI publishing needs no secret either — it uses OIDC,
configured below.

## PyPI trusted publishing

`release.yml`'s `publish-pypi` job uploads to PyPI without an API token. PyPI issues a
short-lived credential per run, but only to a run whose identity matches a publisher you
register on the project. Three things to set up, in this order:

**1. A PyPI account with two-factor authentication.** PyPI requires 2FA to manage a
project, and trusted publishing is configured from the account that will own `anyinfer`.
Enable it first; discovering the requirement mid-release is an avoidable scramble.

**2. The `pypi` environment.** **Settings → Environments → New environment**, named
exactly `pypi`. This is the human gate: add yourself under *Required reviewers* if each
upload should wait for an approval click, and it is also the name PyPI matches on, so it
must exist before the first release run.

Set its *Deployment branches and tags* to **Selected branches** with one rule for `main`.
`release.yml` only publishes from `main` anyway, but that is a property of the workflow
file, which any branch can edit; the environment restriction is enforced by GitHub, so a
branch cannot borrow the environment's publishing identity by rewriting the workflow.

**3. The publisher on PyPI.** On [pypi.org](https://pypi.org) as **anthturner**:

| Field | Value |
|---|---|
| PyPI project name | `anyinfer` |
| Owner | `anthturner` |
| Repository name | `AnyInfer` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Spell the owner and repository exactly as GitHub shows them: those values are compared
against the OIDC claims of each run, which carry the repository's canonical casing.

For a project that has never been published, use **Your projects → Publishing → Add a
pending publisher** — it reserves the name `anyinfer` and creates the project on the
first successful upload, so there is no chicken-and-egg step where you must upload a
wheel manually first. For an existing project, the same fields live under **Manage →
Settings → Publishing**. A pending publisher becomes the project's ordinary publisher on
the first successful upload; nothing has to be re-registered afterwards.

Every field is matched exactly on each run. Renaming the repository, transferring it to a
different owner, or renaming `release.yml` silently invalidates the publisher — the next
upload fails until the registration is updated on PyPI.

Breaks without it: the release run's upload step fails with an OIDC/permission error
after the GitHub Release has already been cut — the release stands, the index copy is
missing, and re-running the job after fixing the configuration completes it.

A fork will not publish: its OIDC claims name the fork's owner and repository, which no
publisher on this project matches, so an upload is rejected rather than misattributed.

## When a release goes wrong

Publishing is the only irreversible step in this repo: a version number on PyPI can be
yanked but never reused, not even after deleting the file. Recovery by failure mode:

| Symptom | What happened | What to do |
|---|---|---|
| Release cut, `publish-pypi` failed | The publisher fields or the `pypi` environment do not match the run | Fix the registration, then **re-run the failed job** from the Actions run page. |
| Upload rejected: file already exists | That version was uploaded before | Nothing to recover. Bump to the next patch version and let it ride to `main` again. |
| A published version is broken | It is on the index and installable | **Yank** it (**Manage → Releases → Yank**): resolvers stop selecting it while existing pins keep working. Then release a fix. Deleting instead burns the number permanently. |
| Release cut from the wrong commit | The tag points somewhere unintended | Delete the GitHub Release *and* its tag, fix `main`, and bump the version — reusing the tag would disagree with whatever PyPI already accepted. |
| Run stuck before uploading | The `pypi` environment is waiting on a required reviewer | Approve the deployment on the run page. A run left pending is failed automatically after 30 days. |

Re-running `publish-pypi` never rebuilds: it downloads the same `library-dist` artifact the
build job produced, so a retry cannot ship different bytes than the ones already attached
to the GitHub Release. That artifact is subject to the repository's normal artifact
retention (90 days by default) — after it expires, re-run the whole workflow rather than
the single job.

## Everything else is code

Deliberately *not* on this page: quality gates, conformance, docs builds, and release
packaging — those are fully described by the workflow files and
[`workspace.py`](https://github.com/anthturner/AnyInfer/blob/main/workspace.py), and
work in any fork with no setup beyond the items above. Live-provider conformance runs
and cassette recording use real provider credentials, but those are operator tasks run
locally, never CI secrets (NOTES.md, remaining work).
