# SASLite

SASLite is a local Python interpreter for a practical subset of the SAS
language. It runs DATA steps, SQL, macros, statistical procedures, reports,
and graphics for local data checks, prototyping, and compatibility testing.

**Version 0.5.0 · Python 3.10+ · MIT**

## Capabilities

- **Data processing:** DATA steps, dataset merges and updates, BY groups,
  arrays, metadata, formats, and common character, numeric, and date functions.
- **SQL and macros:** joins, aggregation, subqueries, table updates, macro
  scopes, loops, quoting, and local includes.
- **Statistics:** descriptive and frequency analysis, correlation, t-tests,
  regression, generalized and mixed models, and survival analysis, including
  supported interval-censored models.
- **Reports and graphics:** REPORT/TABULATE, ODS result datasets, RTF/listing
  reports, SGPLOT/SGPANEL, and a subset of GTL templates rendered as PNGs.
- **Data and projects:** pandas integration, CSV/Excel and SAS file reading,
  XPT writing, compatibility profiles, metadata-driven schemas, and test fixtures.
- **Ways to work:** command line, interactive prompt, Python API, local browser
  GUI, desktop wrapper, and VS Code integration with source diagnostics.

## Documentation

- [Install and run](USAGE.md): CLI, GUI, Python API, and examples.
- [Feature reference and limitations](FEATURES.md): supported syntax and procedures.
- [Project setup](NEW_PROJECT.md): local profiles, metadata, schemas, and fixtures (Russian).
- [ODS compatibility](ODS_COMPATIBILITY.md): output table contracts and RTF styles.
- [Syntax examples](DOCS.md): extended language guide (Chinese; some inherited sections are historical).
- [Development](DEVELOPMENT.md) · [Release notes](CHANGELOG.md) · [Example programs](examples/).

## Compatibility and provenance

SASLite implements a subset of SAS and does not guarantee identical behavior
or statistical results. Check the documented limitations and validate results
against your target SAS environment. SAS7BDAT files can be read, but writes
use XPT content even with a `.sas7bdat` extension.

This is an independently maintained downstream of the MIT-licensed SASLite
0.4.1 PyPI source distribution; see [provenance](DOWNSTREAM.md). Version 0.5.0
refers to this repository. SASLite is not affiliated with, endorsed by, or
supported by SAS Institute Inc. See [LICENSE](LICENSE).
