# Repository setup

The one-time GitHub configuration this repo depends on. Everything here is
*infrastructure state that lives outside the code* — settings and secrets that a fork,
a migration, or a new maintainer must recreate by hand, because no workflow can create
them for itself. Each item below names the workflow that breaks without it.

## Before the first push to `main`

The first commit already declares version `0.1.0`, so its first push to `main` is a real
release: `release.yml` will create `v0.1.0` and attempt the PyPI upload. Create the empty
GitHub repository first, then configure the `pypi` environment and the pending PyPI
publisher described below **before** pushing `main`. This avoids cutting the GitHub Release
while its PyPI identity is still missing.

Pages and branch protection can be configured after the first push, once the branches and
the `ci-ok` check exist. Do not push an unreleased version to `main` merely to bootstrap
repository settings.

## Branch protection

`develop` and `main` are protected and gated on the aggregate **`ci-ok`** status check —
one stable name, so the required check never has to enumerate matrix jobs. The exact
one-time `gh` commands live in [branching and releases](releasing.md).

Breaks without it: nothing *fails*, which is the problem — merges land without the gates.

## GitHub Pages

**Settings → Pages → Source: "GitHub Actions".** The docs site deploys from
`pages.yml` on every merge to `main` and on every published release; the workflow
carries the `pages: write` / `id-token: write` permissions it needs, but the source
selection cannot be set by a workflow.

Breaks without it: `pages.yml` deploy jobs fail; the site never publishes.

## Actions settings

**Settings → Actions → General → Workflow permissions → tick "Allow GitHub Actions to
create and approve pull requests".** The pricing-refresh workflow's proposal stage opens
a pull request with the verified price changes; without this toggle the PR creation is
rejected at the API level even though the workflow's own `permissions:` block requests
`pull-requests: write`.

Two facts about scheduled workflows worth knowing up front:

- The weekly cron in `pricing-refresh.yml` only fires from the **default branch** —
  the workflow file must exist on `main` before the schedule is live.
- GitHub suspends cron schedules in repositories with no activity for ~60 days; the
  Actions tab shows a re-enable banner when that happens.

## Secrets

Configured under **Settings → Secrets and variables → Actions**. `GITHUB_TOKEN` is
provided automatically and is not listed.

| Secret | Used by | Required | What it is |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `pricing-refresh.yml` (propose stage) | One of these two | An Anthropic **Console** API key ([platform.claude.com](https://platform.claude.com) → API keys). Billed per token against the Console account's credits. |
| `CLAUDE_CODE_OAUTH_TOKEN` | `pricing-refresh.yml` (propose stage) | One of these two | A Claude Code OAuth token minted from a **Claude Pro/Max subscription** by running `claude setup-token` on your machine. Draws on the subscription's usage limits instead of per-token billing. |

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

Without either secret, the deterministic drift check still runs weekly and the workflow
summary still surfaces drift; only the automated verify-and-open-a-PR stage fails
(visibly, in the Actions log).

No other workflow needs a secret: `ci.yml`, `release.yml`, and `pages.yml` run entirely
on the automatic `GITHUB_TOKEN`. PyPI publishing needs no secret either — it uses OIDC,
configured below.

## PyPI trusted publishing

`release.yml`'s `publish-pypi` job uploads to PyPI without an API token. PyPI issues a
short-lived credential per run, but only to a run whose identity matches a publisher you
register on the project. Two things to set up, in this order:

**1. The `pypi` environment.** **Settings → Environments → New environment**, named
exactly `pypi`. This is the human gate: add yourself under *Required reviewers* if each
upload should wait for an approval click, and it is also the name PyPI matches on, so it
must exist before the first release run.

**2. The publisher on PyPI.** On [pypi.org](https://pypi.org) as **anthturner**:

| Field | Value |
|---|---|
| Owner | `anthturner` |
| Repository name | `anyinfer` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

For a project that has never been published, use **Your projects → Publishing → Add a
pending publisher** — it reserves the name `anyinfer` and creates the project on the
first successful upload, so there is no chicken-and-egg step where you must upload a
wheel manually first. For an existing project, the same fields live under **Manage →
Settings → Publishing**.

Breaks without it: the release run's upload step fails with an OIDC/permission error
after the GitHub Release has already been cut — the release stands, the index copy is
missing, and re-running the job after fixing the configuration completes it.

A fork will not publish: its OIDC claims name the fork's owner and repository, which no
publisher on this project matches, so an upload is rejected rather than misattributed.

## Everything else is code

Deliberately *not* on this page: quality gates, conformance, docs builds, and release
packaging — those are fully described by the workflow files and
[`workspace.py`](https://github.com/anthturner/anyinfer/blob/main/workspace.py), and
work in any fork with no setup beyond the items above. Live-provider conformance runs
and cassette recording use real provider credentials, but those are operator tasks run
locally, never CI secrets (NOTES.md, remaining work).
