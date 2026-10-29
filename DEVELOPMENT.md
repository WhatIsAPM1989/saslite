# Downstream development workflow

This checkout is intended to be installed in editable mode. Code changes under
`src/saslite/` are then used immediately by the `saslite` command.

## One-time setup

Use Python 3.10 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

The environment is relative to the checkout root:

```text
.venv
```

Keep personal paths and project-specific profiles in `.saslite-private/`
(ignored by Git). The public `example` profile and
`examples/profile_demo.sas` use synthetic data only. To try them from the
checkout root:

```bash
mkdir -p _local/config
# Copy only when no local setup exists; preserve your existing configuration.
test -e _local/config/localsetup.sas || cp examples/localsetup.example.sas _local/config/localsetup.sas
./scripts/run-saslite --profile example --profile-root . examples/profile_demo.sas
```

The copied setup under `_local/` is ignored and can be customized locally.
Existing private profiles continue to work with `--profile-file`; the public
example does not replace them. Share selected Git files, not an archive of
the working directory, which also contains ignored private files.

## Run a SAS program

```bash
.venv/bin/saslite --workdir /tmp/saslite-work program.sas
```

Or use the project shortcut:

```bash
make run PROGRAM=/absolute/path/program.sas
make test
make version
```

The working directory contains generated datasets and must not be committed.

## Fix a compatibility defect

1. Search [issues](https://github.com/WhatIsAPM1989/saslite/issues) and open PRs
   for the same defect. Create an issue if needed, using a minimal synthetic
   reproducer, expected and actual behavior, version, and acceptance criteria.
   Never publish corporate programs, project identifiers, private paths, data,
   or unredacted logs.
2. Create an isolated worktree from current `origin/main` on an issue branch,
   for example `codex/issue-123-empty-count`. Keep the shared SASLite checkout
   stable while SAS project checks run against it. Each unrelated fix needs its
   own issue branch and PR.
3. Add a regression test under `tests/` that fails before the fix, then make the
   smallest change under `src/saslite/` that restores SAS semantics.
4. Run the affected tests and all downstream tests:

   ```bash
   make test
   ```

   The suite includes both unittest classes and pytest functions, so unittest
   discovery alone does not run every test.
5. When private local inputs are available, re-run the original program
   unchanged against the fixed worktree and validate output values, not only
   the exit code. Record a sanitized result or state that this check is pending.
6. Commit the regression test and implementation together, push the issue
   branch, and open a PR targeting `main`. Include `Fixes #<number>`, the
   before/after behavior, test results, and limitations. Use a draft PR if work
   or checks remain incomplete.
7. The user reviews and authorizes merging. After merge, update the shared
   checkout and reinstall it if package metadata or dependencies changed.
   A version bump and release are a separate, explicit action.

GitHub holds the issues, branches, review, and history. Code can be executed in
a local worktree or a remote environment. Moving review to GitHub does not
require uploading private SAS programs or data.

## Instructions for agents in SAS projects

SAS project repositories have their own `AGENTS.md`. Add the following rule
there, replacing instructions that tell agents to fix the shared interpreter
immediately:

> When a run suggests a SASLite defect, reduce it to a synthetic reproducer and
> search or create an issue in `WhatIsAPM1989/saslite` before changing the
> interpreter. Develop the fix in an isolated issue worktree, add a regression
> test, and open a PR with `Fixes #<number>`. Do not modify the shared SASLite
> checkout used by other projects. Leave merging and updating that shared
> installation to the user. Never publish corporate SAS code, private project
> names, data, profiles, paths, or unredacted logs.

Repository instructions apply within that repository. Adding SASLite's
`AGENTS.md` does not update instructions in sibling SAS projects or messages
already loaded by running chats.

The official SAS environment remains the final validation target. SASLite is a
compatibility runtime, not evidence that a program is production-validated.
