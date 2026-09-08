# Feature reference

This is the downstream 0.5.0 feature overview. Support is a subset of SAS;
procedure availability does not imply every SAS option or numerical algorithm.
See [USAGE.md](USAGE.md) for setup and execution.

## Language and procedures

SASLite includes support for:

### Data Processing
- **DATA step**: `DATA`, `SET`, `MERGE`, `INPUT`, `DATALINES`, `INFILE`, `OUTPUT`,
  `KEEP`, `DROP`, `RENAME`, `WHERE`, `IF/THEN/ELSE`, `DO/END`, `DO WHILE/UNTIL`,
  `BY`, `FIRST.` and `LAST.`, `ARRAY`, `RETAIN`, `LENGTH`, `ATTRIB`
- **Additional DATA step support**: `UPDATE`, dataset options, variable lists,
  descriptor metadata, observation limits, and zero-row datasets.
- **Column-mode INPUT**: Fixed-width data reading with position specifications
- **INFILE options**: DLM=, DSD, TRUNCOVER, FIRSTOBS, OBS

### SQL & Queries
- **PROC SQL**: `SELECT`, `CREATE TABLE`, `INSERT`, `UPDATE`, `DELETE`
- **Joins**: INNER, LEFT, RIGHT, FULL OUTER, CROSS
- **Advanced**: Subqueries, `GROUP BY`, `HAVING`, `ORDER BY`, `DISTINCT`
- **Window functions**: `ROW_NUMBER()`, `RANK()`, `LAG()`, `LEAD()`,
  `SUM() OVER`, `AVG() OVER` with `PARTITION BY` and `ORDER BY`
- **Operators**: `CASE`, `LIKE`, `BETWEEN`, `IN`, `IS NULL`, `EXISTS`
- **Aggregate functions**: `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `STD`, `VAR`

### Statistical Analysis
- **PROC MEANS/SUMMARY**: Descriptive statistics with `CLASS`, `BY`, `VAR`, `OUTPUT`
- **PROC FREQ**: One-way and n-way frequency tables, weights, BY groups,
  chi-square and Fisher tests, association measures, cumulative statistics,
  and SAS-named ODS tables
- **PROC CORR**: Correlation analysis (Pearson, Spearman, Kendall)
- **PROC TTEST**: T-tests for comparing means
- **PROC REG**: Linear regression analysis
  - Simple and multiple regression
  - R², Adjusted R², F-statistic, ANOVA tables
  - Residual analysis, VIF for multicollinearity
  - Standardized coefficients
- **PROC LOGISTIC**: Logistic regression
  - Binary logistic regression
  - CLASS statement for categorical variables
  - ODDSRATIO statement with confidence intervals
  - Model fit statistics (AIC, BIC, -2 Log L)
  - Predicted probabilities
- **PROC PHREG**: Cox proportional-hazards models with CLASS, STRATA, BY,
  Efron/Breslow ties, hazard ratios, profile limits for one-parameter models,
  and model diagnostics through ODS
- **PROC MIXED**: Fixed-effect and repeated-measures models with VC, CS, UN,
  AR(1), ARH(1), TOEP, and TOEPH covariance structures; solutions, Type 3
  tests, LS-means, differences, covariance matrices, and fit tables

- **PROC UNIVARIATE**: distribution summaries and quantiles for supported syntax.
- **PROC GENMOD**: supported generalized linear model syntax, CLASS effects,
  contrasts, and ODS results; see `tests/test_proc_genmod.py` for covered cases.
- **PROC LIFETEST / ICLIFETEST**: right-censored and interval-censored survival
  analysis for the supported syntax.
- **PROC ICPHREG**: interval-censored proportional-hazards models with the
  supported piecewise baseline, strata, and hazard-ratio output.

### Other Procedures
- **PROC SORT**: Multi-key sorting with `BY`, `DESCENDING`, `NODUPKEY`
- **PROC PRINT**: Data display with `VAR`, `WHERE`, `BY`
- **PROC REPORT**: `COLUMN`/`DEFINE`, grouping and analysis columns, `OUT=`,
  `ACROSS`, BY groups, summary `RBREAK`, and `Report` ODS output, plus file
  output through `ODS RTF FILE=` and `ODS LISTING FILE=`
- **PROC TABULATE**: row/column dimensions, crossed class/analysis variables,
  multiple statistics, `ALL`, BY groups, and `Table` ODS output
- **PROC TRANSPOSE / FORMAT**: dataset reshaping and user-defined formats,
  including CNTLIN input.
- **PROC CONTENTS**: Dataset metadata
- **PROC DATASETS**: Library management, dataset operations
- **PROC COMPARE / COPY**: dataset comparison and library copying.
- **PROC APPEND**: Append datasets
- **PROC IMPORT/EXPORT**: CSV and delimited file I/O

### Macro System
- **Macro variables and scopes**: `%LET`, `%GLOBAL`, `%LOCAL`, `%SYMDEL`,
  indirect `&&` references, and recursive rescanning
- **Macros and control flow**: positional/keyword/default parameters, nested and
  recursive `%MACRO` calls, `%IF/%THEN/%ELSE`, iterative `%DO`, `%DO %WHILE`,
  `%DO %UNTIL`, `%GOTO`, and `%RETURN`
- **Macro functions**: `%EVAL`, `%SYSEVALF`, character functions, symbol-table
  queries, and compile-time/runtime quoting (`%STR`, `%NRSTR`, `%BQUOTE`,
  `%NRBQUOTE`, `%SUPERQ`, `%UNQUOTE`, and Q variants)
- **%SYSFUNC / %QSYSFUNC**: Call supported DATA step and dataset functions in
  macro code, with optional output formatting
- **%INCLUDE**: Compose programs from multiple files
- **Automatic variables and diagnostics**: common `SYS*` variables plus
  `MPRINT`, `MLOGIC`, and `SYMBOLGEN` output

### Built-in Functions
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
The exact ODS object contract for statistical and presentation procedures is
listed in `ODS_COMPATIBILITY.md`.

## Statistical graphics

`PROC SGPLOT` and `PROC SGPANEL` render through Matplotlib's headless backend,
so they work on desktops, servers, and CI runners without a display. The local
GUI shows generated graphs in the Output tab:

```sas
proc sgplot data=sales;
  scatter x=height y=weight / group=sex;
  reg x=height y=weight / lineattrs=(pattern=dash thickness=2);
  xaxis label="Height" grid;
  yaxis label="Weight" grid;
  title "Height and weight";
run;

proc sgpanel data=sales;
  panelby sex / columns=2;
  vbar age / response=weight stat=mean;
run;
```

The Python API exposes every image on its producing step as a base64 PNG
artifact, avoiding temporary-file ownership issues:

```python
import base64
from pathlib import Path

result = sas.execute(source)
png = next(step for step in result.steps if step.artifacts).artifacts[0]
Path("graph.png").write_bytes(base64.b64decode(png.data))
```

Basic GTL templates can be compiled in the session and rendered later with
`PROC SGRENDER`:

```sas
proc template;
  define statgraph graphs.scatter;
    begingraph;
      entrytitle graph_title;
      layout overlay / xaxisopts=(label="Height") yaxisopts=(label="Weight");
        scatterplot x=height y=weight / group=sex;
      endlayout;
    endgraph;
  end;
run;

proc sgrender data=sales template=graphs.scatter;
  dynamic graph_title="GTL scatter";
run;
```

## Known limits

SASLite intentionally implements a practical subset of SAS. Some advanced or
environment-specific SAS features are not currently supported:

**Not Implemented:**
- Stored/compiled macro catalogs and SAS autocall (`SASAUTOS`) libraries
- Remote libraries and server integration
- Complete format/informat catalog system
- Complete ODS styling and destination catalog (RTF/LISTING for PROC REPORT
  and ODS OUTPUT datasets for supported statistical procedures are available)
- Legacy graphics procedures such as GPLOT/GCHART
- Some specialized PROCs (for example IML)
- BY-group processing in all contexts
- Full index support
- Hash objects and data structures

**Partial Support:**
- Statistical graphics use a headless Matplotlib backend. `PROC SGPLOT`
  supports scatter, series, step, needle, VLINE/HLINE, VBAR/HBAR, histogram,
  density, regression, LOESS-style smoothing, band, dot, and reference-line
  statements. `PROC SGPANEL` supports `PANELBY`; `PROC TEMPLATE` plus
  `PROC SGRENDER` supports the common GTL `BEGINGRAPH`, `ENTRYTITLE`,
  nested `LAYOUT LATTICE`, `LAYOUT OVERLAY`, and plot-statement subset.
  Lattices support rows/columns, weights, gutters, row/column-major ordering,
  and union data ranges. Graphs are returned as PNG artifacts by the Python
  API and displayed by the built-in GUI.
- Statistical ODS contracts cover the supported binary LOGISTIC, Cox PHREG,
  repeated-measures MIXED, FREQ, REPORT, and TABULATE syntax. Conditional exact
  LOGISTIC, PHREG frailty/Bayesian models, MIXED RANDOM effects, full
  Kenward-Roger adjustment, and advanced FREQ CMH/agreement/binomial analyses
  are not yet implemented
- Macro quoting implements the commonly used masking and rescanning behavior,
  but not every edge case of the SAS word scanner; backward `%GOTO`,
  `PARMBUFF`/`SYSPBUFF`, and macro header options such as `MINOPERATOR` remain
  unsupported
- `%INCLUDE` supports nested local files, but not filerefs or macro-variable
  expansion inside the include path
- PROC PRINT does not support TITLE statements
- Some advanced SQL features (recursive CTEs, complex subqueries)
- Informats and formats (common ones supported)

When SASLite cannot parse or execute a program exactly, simplify the program to
the supported subset or use the Python API to prepare input datasets directly.

**Performance Note:** Stateless numeric DATA steps with one `SET`, column
assignments, `IF`/`WHERE` filters, and common numeric missing-value functions
use a vectorized pandas fast path. Stateful or diagnostic-sensitive constructs
automatically fall back to the observation-by-observation PDV engine. Performance depends on the program and data; no fixed row-count limit or
speedup is guaranteed.

## Project configuration and diagnostics

- Built-in example and external Python compatibility profiles adapt local
  setup and macro conventions without editing original SAS programs.
- `saslite-project.json` configures weak/strict schema policies. Metadata CSVs
  provide descriptors and zero-row datasets, with lineage through WORK.
- Semicolon CSV fixtures override local data and fill omitted manifest columns
  with missing values. The fixture CLI generates headers from metadata.
- Diagnostics report source locations, schema assumptions, missing variables,
  truncation and merge issues. Quiet, fail-fast, and color modes support editor runs.

See [NEW_PROJECT.md](NEW_PROJECT.md) for the full project workflow.
