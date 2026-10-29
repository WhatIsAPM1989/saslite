# SASLite agent instructions

## GitHub workflow

- Use `WhatIsAPM1989/saslite` as the shared issue tracker and source of truth.
- For each new defect, search existing issues and PRs before creating an issue.
  Record a minimal synthetic reproducer, expected and actual behavior, the
  SASLite version or commit, and acceptance criteria before changing code.
- Create fixes in an isolated worktree on `codex/issue-<number>-<short-name>`
  based on current `origin/main`. Do not modify the shared checkout used to run
  SAS projects, include unrelated dirty files, or work directly on `main`.
- Add a regression test that fails before the fix, implement the smallest
  correction, then run the affected tests and the full suite with `make test`.
- Push the issue branch and open a PR targeting `main`, with `Fixes #<number>`,
  a behavior summary, test results, and any remaining limitations. If unfinished
  or failing checks remain, open a draft PR and explain them.
- The user authorizes creating issues and PRs for defects discovered while
  working on SASLite. Do not merge PRs, enable auto-merge, push to `main`, or
  publish releases unless the user explicitly requests that action.
- If GitHub access is unavailable, prepare the issue text locally and report
  the blocker. Do not silently fall back to fixing the shared installation.

## Data and compatibility

- Publish only synthetic, sanitized reproducers. Keep corporate SAS sources,
  private project names, data, profiles, paths, logs, and outputs out of GitHub.
- Distinguish interpreter defects from SAS program defects and missing local
  inputs. Do not change SAS programs or invent input data to hide runtime gaps.
- Follow `DEVELOPMENT.md` for setup, tests, and validation. Use pytest so both
  unittest classes and standalone GUI tests run.
- Follow the user's standard statement-comment header when creating a SAS
  program or updating its header. Keep actual metadata, aligned fields,
  Usage notes, and genuine revision history. Do not invent unknown values.
