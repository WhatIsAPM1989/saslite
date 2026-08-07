# Downstream development workflow

This checkout is intended to be installed in editable mode. Code changes under
`src/saslite/` are then used immediately by the `saslite` command.

## One-time setup

Use Python 3.10 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

On this workstation the configured Python 3.12 environment is:

```text
/Users/iliaveselovskii/Documents/Workr/SASLite/.venv
```

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

1. Reduce the failure to synthetic input without company or subject data.
2. Add a regression test under `tests/` that fails before the fix.
3. Make the smallest change under `src/saslite/` that restores SAS semantics.
4. Run all downstream tests:

   ```bash
   .venv/bin/python -m unittest discover -s tests -v
   ```

5. Re-run the original local program and validate output values, not only the
   process exit code.
6. Commit the test and implementation together and push to `main`.

The official SAS environment remains the final validation target. SASLite is a
compatibility runtime, not evidence that a program is production-validated.
