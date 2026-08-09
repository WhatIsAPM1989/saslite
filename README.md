# SASLite

> **Downstream repository:** this repository was imported from the official
> `saslite 0.4.1` source distribution on PyPI and is maintained independently.
> It is not the public upstream repository of the PyPI maintainer. See
> [DOWNSTREAM.md](DOWNSTREAM.md) for provenance and the downstream changes.

SASLite is a lightweight local interpreter for a practical subset of the SAS
language, implemented in Python on top of pandas. It is intended for local data
checks, small automation workflows, SAS-like examples, and migration/testing
work where a full SAS runtime is not available.

SASLite is an independent project. It is not affiliated with, endorsed by, or
supported by SAS Institute Inc.

## Status

**Version 0.4.1 - Bug Fix Release**

Critical bug fix for XPT column name handling.

**New in v0.4.1:**
- 🐛 **CRITICAL FIX**: Column name length limit corrected from 8 to 32 characters
- ✅ XPT format properly supports 32-character column names (was incorrectly limited to 8)
- ✅ Fixed "duplicate column name" errors when using CREATE TABLE with long names
- ✅ No more manual column renaming needed for most use cases

**Previous release (v0.4.0):**
- 🎉 **PROC REG** - Linear regression analysis
- 🎉 **PROC LOGISTIC** - Logistic regression with full CLASS and ODDSRATIO support
- ⚡ **25-30% performance improvement**
- 📚 **8 comprehensive examples** with automated validation
- ✅ **540 tests passing** (100% pass rate)

See [CHANGELOG.md](CHANGELOG.md) for complete release notes.

## Installation

The PyPI command below installs the original `0.4.1` release. Until this
downstream publishes a separately named package or release artifact, install a
checkout of this repository to use the downstream fixes.

```bash
pip install saslite
```

Optional extras:

```bash
pip install "saslite[gui]"
```

For local development from a checkout:

```bash
pip install -e ".[gui]"
```

## Command Line

Run a SAS program:

```bash
saslite path/to/program.sas
```

### Devin IDE / VS Code

This repository recommends the Code Runner extension and maps its editor-title
play button to SASLite for `.sas` files. After installing the recommended
extension, open a SAS program and click **Run Code** (the play icon).

Editor runs use a concise fail-fast mode: regular NOTE/table output is hidden,
warnings are yellow, errors are red, and execution stops after the first SAS
step that reports a warning or error. A normal `saslite program.sas` command
continues to use the full uncolored log. The same behavior is available from
the CLI with `--quiet --fail-fast --color always`.

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

Choose storage format (sas7bdat is default, xpt for legacy compatibility):

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

## GUI

Install the GUI extra:

```bash
pip install "saslite[gui]"
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

# Default: uses sas7bdat format for better compatibility
sas = SasInterpreter()

# Or explicitly specify format
sas = SasInterpreter(sas_format='sas7bdat')  # Recommended (default)
sas = SasInterpreter(sas_format='xpt')       # Legacy XPT format

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

### Storage Formats

SASLite supports two storage format options:

- **sas7bdat** (default): Uses .sas7bdat file extension for better tool compatibility
- **xpt**: Uses .xpt file extension (SAS Transport format)

**Important Note:** Due to Python library limitations, both formats currently use the XPT (Transport) file format internally. This means:
- Column names are limited to 32 characters (XPT format constraint)
- Files use the XPT binary format regardless of extension
- Files are fully compatible with SAS software and other SAS readers
- The XPT format is actually quite robust: stable, well-documented, and has excellent library support

**Version 0.4.1 Note:** The column name limit was corrected from an incorrect 8-character limit to the proper 32-character limit specified by the XPT format.

The format can be configured via:
- Python API: `SasInterpreter(sas_format='sas7bdat')` or `SasInterpreter(sas_format='xpt')`
- CLI: `saslite --format sas7bdat` or `saslite --format xpt`
- Direct backend: `SasBackend('./work', format='sas7bdat')`

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

## Supported Features

SASLite includes support for:

### Data Processing
- **DATA step**: `DATA`, `SET`, `MERGE`, `INPUT`, `DATALINES`, `INFILE`, `OUTPUT`,
  `KEEP`, `DROP`, `RENAME`, `WHERE`, `IF/THEN/ELSE`, `DO/END`, `DO WHILE/UNTIL`,
  `BY`, `FIRST.` and `LAST.`, `ARRAY`, `RETAIN`, `LENGTH`, `ATTRIB`
- **Column-mode INPUT**: Fixed-width data reading with position specifications
- **INFILE options**: DLM=, DSD, TRUNCOVER, FIRSTOBS, OBS

### SQL & Queries
- **PROC SQL**: `SELECT`, `CREATE TABLE`, `INSERT`, `UPDATE`, `DELETE`
- **Joins**: INNER, LEFT, RIGHT, FULL OUTER, CROSS
- **Advanced**: Subqueries, `GROUP BY`, `HAVING`, `ORDER BY`, `DISTINCT`
- **Window functions** (new in 0.4.0): `ROW_NUMBER()`, `RANK()`, `LAG()`, `LEAD()`,
  `SUM() OVER`, `AVG() OVER` with `PARTITION BY` and `ORDER BY`
- **Operators**: `CASE`, `LIKE`, `BETWEEN`, `IN`, `IS NULL`, `EXISTS`
- **Aggregate functions**: `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `STD`, `VAR`

### Statistical Analysis
- **PROC MEANS/SUMMARY**: Descriptive statistics with `CLASS`, `BY`, `VAR`, `OUTPUT`
- **PROC FREQ**: Frequency tables, cross-tabulations, chi-square tests
- **PROC CORR** (new in 0.3.0): Correlation analysis (Pearson, Spearman, Kendall)
- **PROC TTEST** (new in 0.3.0): T-tests for comparing means
- **PROC REG** (new in 0.4.0): Linear regression analysis
  - Simple and multiple regression
  - R², Adjusted R², F-statistic, ANOVA tables
  - Residual analysis, VIF for multicollinearity
  - Standardized coefficients
- **PROC LOGISTIC** (new in 0.4.0): Logistic regression
  - Binary logistic regression
  - CLASS statement for categorical variables
  - ODDSRATIO statement with confidence intervals
  - Model fit statistics (AIC, BIC, -2 Log L)
  - Predicted probabilities

### Other Procedures
- **PROC SORT**: Multi-key sorting with `BY`, `DESCENDING`, `NODUPKEY`
- **PROC PRINT**: Data display with `VAR`, `WHERE`, `BY`
- **PROC CONTENTS**: Dataset metadata
- **PROC DATASETS**: Library management, dataset operations
- **PROC APPEND**: Append datasets
- **PROC IMPORT/EXPORT**: CSV and delimited file I/O

### Macro System
- **Macro variables**: `%LET`, `%PUT`, macro variable resolution
- **Macro functions**: `%MACRO`, `%MEND`, `%DO`, `%IF/%THEN/%ELSE`
- **%SYSFUNC** (new in 0.3.0): Call DATA step functions in macro code
- **%INCLUDE**: Compose programs from multiple files
- **Conditional logic**: `%IF`, `%DO WHILE`, `%DO UNTIL`

### Built-in Functions (82 functions)
- **Character**: `STRIP`, `UPCASE`, `LOWCASE`, `SUBSTR`, `INDEX`, `SCAN`, 
  `CAT`, `CATX`, `TRIM`, `LEFT`, `RIGHT`, `COMPRESS`, `TRANSLATE`, `REVERSE`,
  `REPEAT`, `COMPARE`, `COMPBL`, `QUOTE`, `DEQUOTE`, `COUNTC`, `COUNTW`
- **Numeric**: `SUM`, `MEAN`, `MIN`, `MAX`, `ROUND`, `CEIL`, `FLOOR`, `ABS`,
  `SQRT`, `EXP`, `LOG`, `LOG10`, `MOD`, `SIGN`, `INT`, `RANUNI`, `RANNOR`
- **Date/Time**: `TODAY`, `DATE`, `DATETIME`, `DATEPART`, `TIMEPART`, `YEAR`,
  `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`, `WEEKDAY`, `QTR`, `MDY`,
  `INTNX`, `INTCK`, `DHMS`, `HMS`, `YYQ`, `WEEK`
- **Conversion**: `INPUT`, `PUT`, `INPUTN`, `INPUTC`, `PUTN`, `PUTC`
- **Missing values**: `NMISS`, `CMISS`, `MISSING`, `COALESCE`, `COALESCEC`
- **Utility**: `N`, `DIM`, `IFN`, `IFERROR`, `LAG`, `DIF`
- **Statistical**: `PROBNORM`, `PROBT`, `PROBCHI`, `PROBF`

### Libraries & I/O
- **LIBNAME**: Local work areas, reference libraries
- **CSV support**: PROC IMPORT/EXPORT for CSV files
- **Python API**: Create datasets from pandas, export to pandas
- **Excel support**: PROC IMPORT/EXPORT for XLSX files

See `DOCS.md` and the `examples/` directory for detailed usage.

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

See the `examples/` directory for 8 comprehensive examples:
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

Validate all examples:

```bash
cd examples
python validate_examples.py
```

## Known Limits

SASLite intentionally implements a practical subset of SAS. Some advanced or
environment-specific SAS features are not currently supported:

**Not Implemented:**
- Advanced macro features (MACRO PROC, compiled macros)
- Remote libraries and server integration
- Complete format/informat catalog system
- ODS (Output Delivery System)
- Graphics procedures (SGPLOT, GPLOT, etc.)
- Some specialized PROCs (IML, REPORT, TABULATE, etc.)
- BY-group processing in all contexts
- Full index support
- Hash objects and data structures

**Partial Support:**
- PROC PRINT does not support TITLE statements
- ARRAY syntax: use full variable lists instead of `score1-score4` shorthand
- Some advanced SQL features (recursive CTEs, complex subqueries)
- Informats and formats (common ones supported)

When SASLite cannot parse or execute a program exactly, simplify the program to
the supported subset or use the Python API to prepare input datasets directly.

**Performance Note:** SASLite is optimized for datasets up to ~1M rows. For larger
datasets, consider using SAS itself or chunking strategies with the Python API.

## Development

Install development dependencies:

```bash
pip install -e ".[excel,gui]"
pip install pytest build twine
```

Run tests:

```bash
python -m pytest -q
```

Build distribution artifacts:

```bash
python -m build
```

Check package metadata:

```bash
python -m twine check dist/*
```

## Publishing

Test the package on TestPyPI before publishing to PyPI:

```bash
python -m build
python -m twine upload --repository testpypi dist/*
```

After verifying installation from TestPyPI, publish the same version to PyPI:

```bash
python -m twine upload dist/*
```

## License

SASLite is distributed under the MIT License. See `LICENSE` for details.
