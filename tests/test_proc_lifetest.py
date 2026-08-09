import unittest

from saslite import SasInterpreter


class ProcLifetestTests(unittest.TestCase):
    def test_kaplan_meier_quartiles_and_survival_plot(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  input arm time cnsr;
  datalines;
1 5 0
1 6 1
2 8 0
2 10 0
;
run;
ods exclude all;
ods graphics on;
ods output Quartiles=quartiles SurvivalPlot=survival_plot;
proc lifetest data=adtte plots=survival(atrisk=0 to 10 by 5);
  time time*cnsr(1);
  strata arm;
run;
ods output close;
ods graphics off;
ods select all;
"""
        )

        self.assertTrue(result.success, result.error)
        quartiles = sas.get_dataset("WORK", "QUARTILES")
        medians = quartiles[quartiles["PERCENT"] == 50]
        self.assertEqual(medians["ESTIMATE"].tolist(), [5.0, 8.0])
        self.assertIn("LOWERLIMIT", quartiles.columns)
        plot = sas.get_dataset("WORK", "SURVIVAL_PLOT")
        risk = plot[plot["TATRISK"].notna()]
        self.assertEqual(sorted(risk["TATRISK"].unique().tolist()), [0.0, 5.0, 10.0])
        self.assertIn("STRATUMNUM", plot.columns)

    def test_where_and_output_dataset_options(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  input arm time cnsr include;
  datalines;
1 4 0 1
1 8 0 1
2 3 0 0
;
run;
ods output Quartiles=medians(where=(percent=50));
proc lifetest data=adtte(where=(include=1)) method=km;
  time time*cnsr(1);
  strata arm;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        medians = sas.get_dataset("WORK", "MEDIANS")
        self.assertEqual(len(medians), 1)
        self.assertEqual(medians["ESTIMATE"].iloc[0], 4.0)

    def test_reports_missing_analysis_variable(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  time=1;
run;
proc lifetest data=adtte;
  time time*cnsr(1);
run;
"""
        )

        self.assertFalse(result.success)
        errors = [step.error for step in result.steps if step.error]
        self.assertTrue(any("CNSR" in error for error in errors))

    def test_logrank_homtests_output(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  input arm time cnsr;
  datalines;
1 1 0
1 2 0
1 3 0
2 7 0
2 8 0
2 9 0
;
run;
ods output HomTests=homtests LogUniChiSq=logrank;
proc lifetest data=adtte;
  time time*cnsr(1);
  strata arm;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        homtests = sas.get_dataset("WORK", "HOMTESTS")
        self.assertEqual(homtests["TEST"].tolist(), ["Log-Rank"])
        self.assertEqual(homtests["DF"].iloc[0], 1)
        self.assertLess(homtests["PROBCHISQ"].iloc[0], 0.05)
        logrank = sas.get_dataset("WORK", "LOGRANK")
        self.assertAlmostEqual(
            logrank["PROBCHISQ"].iloc[0],
            homtests["PROBCHISQ"].iloc[0],
        )


if __name__ == "__main__":
    unittest.main()
