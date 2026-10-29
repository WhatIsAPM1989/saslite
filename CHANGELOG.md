# Release notes

## Unreleased

## 0.6.0 — 2026-10-29

- Added implicit arrays, `DO OVER`, compile-time declarations in nested blocks,
  DATA step `ABORT CANCEL`, and diagnostics for uninitialized declarations.
- Added session-aware `GETOPTION`, runtime macro return handling, and percent
  escapes in macro quoting.
- Fixed SQL counts and HAVING on empty inputs, joined wildcard column names,
  and numeric metadata propagation.
- Expanded PROC TRANSPOSE prefix and output options, PROC IMPORT DATAROW,
  PROC REPORT computed columns, and PROC LIFETEST BY groups, ALPHA, and empty
  output descriptors.
- Added GitHub issue and PR templates and agent workflow instructions.

- Accept omitted function arguments, character ATTRIB lengths, PROC SORT
  DUPOUT=, and the PROC FREQ LIST option.
- Evaluate unaliased SQL expressions, including dictionary.columns SELECT INTO.
- Capture macro loop values per iteration; defer conditional %PUT until its
  branch is selected, and stop execution on %ABORT CANCEL.
- Honor COMPRESS character-class modifiers and zero-padded Zw.d formats.
- Count PUT/%PUT warning and error prefixes and populate RunSummary.log_lines
  independently of console quiet mode.
- Parse global TITLE/FOOTNOTE, ODS PATH/ESCAPECHAR, and PROC REPORT grouped
  columns and aliases. Basic COMPUTE BEFORE/AFTER blocks with literal LINE
  statements are syntax-checked with an explicit warning that they are not
  rendered; other COMPUTE syntax remains unsupported.

## 0.5.0 — 2026-09-08

First minor release of this independently maintained downstream, based on
the original 0.4.1 source distribution.

- Expanded DATA step, SQL, macro processing, and source diagnostics.
- Added project compatibility profiles, metadata-driven schema policies,
  zero-row datasets, and CSV fixtures.
- Expanded statistical procedures, survival models, and ODS output contracts.
- Added statistical graphics and RTF report styling.
- Reorganized documentation into a short overview, run guide, and feature reference.
- Removed client identifiers and personal filesystem paths from public history.

See [FEATURES.md](FEATURES.md) for coverage and numerical limitations, and
[DOWNSTREAM.md](DOWNSTREAM.md) for the original source and license.
