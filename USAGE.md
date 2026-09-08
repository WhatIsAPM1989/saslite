# Running SASLite

## Install this downstream checkout

Requires Python 3.10 or newer. Install from this repository to use version
0.5.0; installing `saslite` by name from PyPI does not select this downstream.

```bash
git clone https://github.com/WhatIsAPM1989/saslite.git
cd saslite
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell.
For the browser GUI and desktop wrapper, install the optional dependencies:

```bash
python -m pip install -e ".[gui]"
```

## Command line

Run a SAS program:

```bash
saslite path/to/program.sas
```

### Devin IDE / VS Code

This repository recommends the Code Runner extension and maps its editor-title
play button to SASLite for `.sas` files. After installing the recommended
extension, open a SAS program and click **Run Code** (the play icon).

Editor runs use a concise fail-fast mode: regular NOTE/table output is hidden,
warnings are yellow, errors are red, recognized problem-variable names are
cyan, and execution stops after the first SAS step that reports a warning or
error. A normal `saslite program.sas` command continues to use the full
uncolored log. The same behavior is available from the CLI with
`--quiet --fail-fast --color always`. A clean editor run prints a green
`SUCCESS: Program completed without warnings or errors.` confirmation.

Diagnostics include `path:line:column` locations. In Devin and VS Code's
integrated terminal, click that location to open the SAS file and place the
cursor at the reported expression or step.

The optional local `vscode/saslite-runner-menu` extension adds **SASLite: Run
with Full Log** to the Run dropdown. That action keeps colored diagnostics but
shows the complete log and does not stop on warnings.

The runner uses `.venv/bin/python` when the repository virtual environment is
available, otherwise it falls back to `python3`. It always runs the local
sources from `src/` and stores persistent datasets in `.work/`.

If the Python dependencies are not installed yet, prepare the environment with:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Without Code Runner, use **Tasks: Run Test Task** from the command palette to
run the current SAS file.

Run one statement:

```bash
saslite -e "data demo; x = 1; output; run;"
```

Start the interactive prompt:

```bash
saslite --interactive
```

Use a persistent working directory for local datasets:

```bash
saslite --workdir ./work path/to/program.sas
```

Choose storage format (sas7bdat is the default extension; both write XPT content):

```bash
saslite --workdir ./work --format sas7bdat path/to/program.sas
saslite --workdir ./work --format xpt path/to/program.sas
```

### Environment compatibility profiles

The public package includes an anonymized example profile:

```bash
saslite --profile example --profile-root /path/to/example-project program.sas
```

It demonstrates project-root discovery, loading
`_local/config/localsetup.sas`, supplying a compatibility macro, and redirecting
an example shared Excel path to `_local/output/excel/`. The tracked SAS source
is not modified.

Real project profiles can remain in a private repository or ignored local
directory. Load one explicitly as trusted Python code:

```bash
saslite \
  --profile-file /private/project/saslite_profile.py \
  --profile-root /private/project \
  program.sas
```

The external module must define
`create_profile(*, project_root=None)` and return a
`saslite.profiles.CompatibilityProfile`. Do not load profile files from an
untrusted source.

### Project schema policies

Create a project structure with:

```bash
./scripts/create-saslite-project.py /path/to/new-project
```

The generated `saslite-project.json` contains project-wide settings:

```json
{
  "version": 1,
  "default_schema": "weak",
  "metadata_dir": "_local/config/metadata",
  "fixtures_dir": "fixtures"
}
```

The CLI discovers the file under `--profile-root` or beside the input SAS
program. Use `--project-file /path/to/saslite-project.json` to select it
explicitly.

SASLite scans every metadata CSV in that directory. A file such as `sdtm.csv`
automatically makes `SDTM` strict; libraries without metadata use
`default_schema`. Strict metadata supplies full descriptors and zero-row
schema-only datasets. When local XPT/SAS7BDAT rows exist, they are viewed through
the manifest descriptor without modifying the source file.

After copying metadata from the SAS log, remove form-feed page breaks and
`The SAS System` page headers with the cleaner generated in that directory:

```bash
python3 _local/config/metadata/clean-sas-log-metadata.py
```

It cleans every metadata CSV beside it and retains the original as a `.bak` file.

With `weak`, an absent source variable uses missing-value semantics and is
reported as an assumption. With metadata-driven `strict`, a variable absent
from the manifest emits a schema warning. Both policies follow source lineage
through intermediate `WORK` datasets.

Variables read without an input dataset remain ordinary uninitialized-variable
warnings.

Dummy rows can be stored as UTF-8 semicolon CSV files under
`fixtures/<LIBREF>/<DATASET>.csv`. A fixture takes precedence over a local
XPT/SAS7BDAT file and is overlaid on the complete manifest descriptor; omitted
columns become missing. Scaffold a fixture header from strict metadata with:

```bash
saslite-fixture SDTM.AE --project-root /path/to/project
```

### Starting a new local project

The new-project workflow, including automatic metadata-driven strict schemas,
the project generator, dummy fixtures, and metadata export, is documented in
[NEW_PROJECT.md](NEW_PROJECT.md).

## GUI

Install the GUI extra:

```bash
python -m pip install -e ".[gui]"
```

Start the browser-based GUI:

```bash
saslite-gui
```

This starts a local Flask server at `http://127.0.0.1:5000` and opens it in the
default browser. To keep it from opening a browser tab automatically:

```bash
saslite-gui --no-browser
```

Start the desktop wrapper, powered by pywebview:

```bash
saslite-desktop
```

On Windows, the desktop wrapper may require Microsoft Edge WebView2 Runtime.
The browser-based `saslite-gui` command is the simpler fallback.

## Python API

```python
from saslite import SasInterpreter

# Default output extension; files are written in XPT format
sas = SasInterpreter()

# Or explicitly specify format
sas = SasInterpreter(sas_format='sas7bdat')  # Default extension
sas = SasInterpreter(sas_format='xpt')       # Explicit XPT extension

result = sas.execute(
    """
    data work.employees;
        input name $ age salary;
        datalines;
    Alice 30 50000
    Bob 25 40000
    ;
    run;

    proc print data=work.employees;
    run;
    """
)

print(result.success)
df = sas.get_dataset("WORK", "EMPLOYEES")
print(df)
```

### Storage formats

SASLite reads SAS7BDAT and XPT files through pyreadstat. Writes use XPT
content even when the selected filename extension is `.sas7bdat`; it is not
a native SAS7BDAT writer. Use `--format xpt` for an explicit XPT filename.
Check interchange files with the target tool before relying on them.

Create a SASLite dataset from pandas:

```python
import pandas as pd
from saslite import SasInterpreter

sas = SasInterpreter()
source = pd.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30]})
sas.create_dataset("source", source)

sas.execute(
    """
    data work.result;
        set work.source;
        doubled = value * 2;
    run;
    """
)

result = sas.get_dataset("WORK", "RESULT")
```

## Examples

### Basic DATA Step and SQL

```sas
data work.sales;
    input region $ product $ amount;
    datalines;
East Widget 100
West Gadget 200
East Widget 150
;
run;

proc sql;
    create table work.summary as
    select region, sum(amount) as total_sales
    from work.sales
    group by region
    order by total_sales desc;
quit;
```

### Statistical Analysis - Linear Regression

```sas
data work.study;
    input hours_studied score;
    datalines;
2 65
4 75
6 85
8 92
;
run;

proc reg data=work.study;
    model score = hours_studied;
    output out=work.predicted predicted=pred_score residual=resid;
run;
```

### Logistic Regression with Categorical Variables

```sas
data work.patients;
    input age treatment $ outcome;
    datalines;
30 A 1
40 B 0
50 A 1
;
run;

proc logistic data=work.patients;
    class treatment;
    model outcome = age treatment;
    oddsratio age;
    oddsratio treatment;
run;
```

### More Examples

See the `examples/` directory for runnable examples:
- `01_hello_world.sas` - Basic DATA Step
- `02_proc_sql.sas` - SQL with window functions
- `03_macro_programming.sas` - Macros and %SYSFUNC
- `04_statistical_analysis.sas` - MEANS, FREQ, CORR, TTEST
- `05_linear_regression.sas` - PROC REG
- `06_logistic_regression.sas` - PROC LOGISTIC
- `07_advanced_data_manipulation.sas` - Functions and arrays
- `08_import_export.sas` - CSV I/O

Run examples with:

```bash
saslite examples/05_linear_regression.sas
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the regression test suite.
