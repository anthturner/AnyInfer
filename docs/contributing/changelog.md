# The Changelog

[`CHANGELOG.md`](https://github.com/anthturner/AnyInfer/blob/main/CHANGELOG.md) is the
short answer to "what changed in this version, and does it affect me?" It is written for
someone who integrates the SDK, ships against the OpenAI-compatible sidecar, or runs the
demo app — not for someone reconstructing the development history. Git already holds the
history, and a release that took 119 commits is not more legible for having 119 lines
about it.

So the changelog is deliberately lossy. Most commits in a release do not appear in it,
and that is the design rather than an omission.

## What Goes In

In priority order, because this order also decides what survives when a release has more
candidates than the entry budget below allows:

1. **Public API and configuration changes** — typed surfaces, config schema, error
   classes, anything that changes what a caller writes or what they get back.
2. **Provider and capability bindings** — a provider gained or lost, or an operation
   (chat, embed, rerank) was bound onto one it did not support before.
3. **Behavior changes** in routing, fallback, budgets, or supervision, where the same
   code now does something different.
4. **Critical bugfixes** — wrong results, credential handling, crashes, resource leaks,
   data loss. Not every fix; the ones a partner would want to know they were exposed to.
5. **Demo app and sidecar changes** a user of those applications would notice.
6. **Support-floor changes** — Python versions, extras, bundle platforms, anything that
   changes whether an install still works.

## What Stays Out

Internal refactors, test changes, CI and workflow edits, documentation, formatting, plan
and status bookkeeping, and dependency bumps that do not move a support floor.

The test is observability, not effort: if the change cannot be detected from outside the
process by someone using AnyInfer, it does not belong here no matter how much work it
was.

## Form

`## Unreleased` sits at the top and always exists, empty or not. Released versions follow
it, newest first:

```markdown
## Unreleased

### Added
- One line, imperative, describing what a caller can now do.

## 0.2.0 — 2026-09-14

### Added
- One line, describing what a caller could do as of this version.

### Fixed
- One line, describing what was wrong rather than which commit fixed it.
```

The rules the [validator](https://github.com/anthturner/AnyInfer/blob/main/scripts/validate_changelog.py)
enforces mechanically:

- Headings come from `Breaking`, `Added`, `Changed`, `Fixed`, in that order. Any may be
  omitted; nothing else is allowed. A fixed vocabulary is what makes the file skimmable,
  and it doubles as the relevance test — an entry that fits none of the four is usually
  an entry that belongs in the commit log instead.
- One bullet per entry, at most 160 characters — measured on the entry's text with its
  Markdown line wrapping collapsed, so wrapping to the repository's line width costs
  nothing and writing three sentences costs what it should.
- No commit hashes, no pull request numbers, no `@author` credits. The release page
  already links all three, and none of them answer "does this affect me?".
- At most 15 entries in a released section. A release that reaches the cap must close
  its section with a line linking the full compare view, so a reader can tell the list
  was curated rather than assume it was complete. `Unreleased` is exempt while it accrues
  — the budget bites at promotion, which is the moment the list is finished.
- **The frontier exception**: at most one entry per release may run long — up to about
  600 characters across indented continuation lines — when the release introduces a
  genuinely new capability class rather than another increment. It should link the
  concept or guide page that explains the thing, not try to explain it inline.

Write for someone who has not been following along. "Naming a target redirects a call; it
does not discard its policy" tells a partner what changed. "Fix target resolution"
does not.

## How an Entry Gets Written

Entries accrue as work merges, not at release time. The
[changelog workflow](https://github.com/anthturner/AnyInfer/blob/main/.github/workflows/changelog.yml)
has two modes:

**Draft**, when a pull request opens into `develop`. It reads this page and the branch's
commits, writes what qualifies into `## Unreleased`, and pushes that commit onto the
branch. Most branches earn an entry or two; a branch confined to tests, CI, refactoring,
or documentation earns none, and the workflow writes nothing rather than inventing
something. It runs once per pull request and skips a branch that already touches
`CHANGELOG.md`, so an entry you edit in review stays edited.

**Promote**, when a push to a feature branch declares a version that has no tag and no
section. `## Unreleased` is renamed to `## <version> — <date>` in place and a fresh empty
`## Unreleased` opens above it. This step is mechanical rather than a rewrite: the entries
were agreed when each branch merged, and cutting a release must not be an opportunity to
reword them. A model is invoked afterwards only if the promoted section fails its own
rules — usually because it accrued past the entry budget — and then only to curate what is
already there.

Feature branches carry no protection rules, which is the whole reason both modes write
there rather than on the `develop` → `main` promotion. Nothing pushes to a protected
branch, no additional pull request is opened, and the draft arrives while the work is
still under review.

Edit an entry like any other part of the diff. It is a draft that happens to be written
by a machine, not an output to be accepted as-is.

Once the version reaches `main`, the [release workflow](https://github.com/anthturner/AnyInfer/blob/main/.github/workflows/release.yml)
slices that same section out of the file and passes it as the GitHub Release body. The
release notes and the changelog cannot disagree, because they are the same bytes.

## Released Sections Are Immutable

A version's section is frozen once it has been released. The validator checks this on
every pull request: the sections already on `main` must appear, byte for byte, as the
tail of the file. New sections may only be added above them.

This is what keeps the file from being quietly regenerated. A model asked to "write the
changelog" will happily rewrite last year's entries into its own voice, and nobody
reviewing a version bump would notice. Making history structurally unwritable means the
workflow only ever gets to write the part that is genuinely new.

`Unreleased` is the exception, and deliberately so: it is not released, so it stays fully
editable until the moment it is promoted.

To correct an entry that has already shipped, do what changelogs have always done: note
the correction under `Unreleased`, or fix the prose in the GitHub Release body, which is
editable. Rewriting a shipped section is not a supported edit.
