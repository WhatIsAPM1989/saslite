# ODS compatibility contract

SASLite treats ODS object names case-insensitively and preserves duplicate
assignments, including target data-set options such as `WHERE=`, `KEEP=`,
`DROP=`, and `RENAME=`. The following objects are produced for the syntax the
corresponding procedure currently supports.

| Procedure | ODS objects |
|---|---|
| REPORT | `Report` |
| TABULATE | `Table` |
| FREQ | `OneWayFreqs`, `CrossTabFreqs`, `ChiSq`, `FishersExact`, `Measures`, `NLevels` |
| LOGISTIC | `ModelInfo`, `NObs`, `ResponseProfile`, `ClassLevelInfo`, `ConvergenceStatus`, `IterHistory`, `FitStatistics`, `GlobalTests`, `ParameterEstimates`, `OddsRatios`, `Association`, `Classification`, `Type3`/`ModelANOVA`, `RSquare` |
| PHREG | `ModelInfo`, `NObs`, `ClassLevelInfo`, `ConvergenceStatus`, `IterHistory`, `LastGradient`, `FitStatistics`, `GlobalTests`, `ParameterEstimates`, `HazardRatios`, `CovB`, `CorrB`, `SimpleStatistics` |
| MIXED | `ModelInfo`, `Dimensions`, `NObs`, `IterHistory`, `ConvergenceStatus`, `CovParms`, `FitStatistics`, `SolutionF`, `Tests3`, `LSMeans`, `Diffs`, `R`, `RCorr` |

## Core column schemas

- FREQ frequency objects use SAS-style `Table`, formatted `F_<variable>`,
  analysis variables, `Frequency`, `Percent`, `CumFrequency`, `CumPercent`,
  `RowPercent`, and `ColPercent` columns as applicable. Statistical tables use
  `Statistic`, `DF`, `Value`, and `Prob`.
- LOGISTIC and PHREG parameter objects use `VARIABLE`, `CLASSVAL0`, `DF`,
  `ESTIMATE`, `STDERR`, a Wald statistic, and its chi-square probability.
- MIXED inferential objects use `EFFECT`, numerator/denominator degrees of
  freedom where applicable, `ESTIMATE`, `STDERR`, `TVALUE`/`FVALUE`, and
  `PROBT`/`PROBF`. Confidence-limit objects also include `ALPHA`, `LOWER`, and
  `UPPER`.

Numeric contract tests use independently known likelihood, contingency-table,
hazard-ratio, LS-mean, and contrast results. The remaining unsupported SAS
algorithms are listed under Known Limits in the main documentation; notably,
the current `DDFM=KR` path uses residual degrees of freedom and does not yet
apply the complete Kenward-Roger covariance inflation.
