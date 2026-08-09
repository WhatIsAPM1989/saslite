import math
import unittest

from saslite import SasInterpreter


class ProcGenmodTests(unittest.TestCase):
    def test_binomial_class_contrast_and_local_ods_output(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data trial;
  input trtn response;
  datalines;
1 1
1 1
1 1
1 1
1 1
1 1
1 0
1 0
2 1
2 1
2 0
2 0
2 0
2 0
2 0
2 0
;
run;
proc genmod data=trial;
  class trtn(ref="2");
  model response(event="1") = trtn / dist=bin link=logit lrci type3;
  estimate "Odds Ratio" trtn 1 -1 / exp alpha=0.05;
  ods output Estimates=estimates ParameterEstimates=parameters ModelANOVA=anova;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        estimates = sas.get_dataset("WORK", "ESTIMATES")
        self.assertEqual(estimates["LABEL"].tolist(), ["Odds Ratio"])
        # The two 2x2 odds are 6/2 and 2/6, so OR=9 and beta=log(9).
        self.assertAlmostEqual(
            estimates["LBETAESTIMATE"].iloc[0], math.log(9.0), places=6
        )
        self.assertAlmostEqual(estimates["EXPESTIMATE"].iloc[0], 9.0, places=6)
        self.assertLess(estimates["LOWEREXP"].iloc[0], 9.0)
        self.assertGreater(estimates["UPPEREXP"].iloc[0], 9.0)

        parameters = sas.get_dataset("WORK", "PARAMETERS")
        treatment = parameters[parameters["PARAMETER"] == "TRTN"].iloc[0]
        self.assertEqual(treatment["LEVEL1"], "1")
        self.assertAlmostEqual(treatment["ESTIMATE"], math.log(9.0), places=6)
        self.assertTrue(math.isfinite(treatment["LOWERLRCL"]))
        self.assertTrue(math.isfinite(treatment["UPPERLRCL"]))

        anova = sas.get_dataset("WORK", "ANOVA")
        self.assertEqual(anova["SOURCE"].tolist(), ["TRTN"])
        self.assertEqual(anova["DF"].iloc[0], 1)
        self.assertTrue(math.isfinite(anova["PROBCHISQ"].iloc[0]))

    def test_numeric_adjustment_where_and_ods_before_proc(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data trial;
  input trtn age response include;
  datalines;
1 30 1 1
1 40 1 1
1 50 0 1
1 60 1 1
2 30 0 1
2 40 1 1
2 50 0 1
2 60 0 1
2 70 1 0
;
run;
ods output Estimates=adjusted;
proc genmod data=trial(where=(include=1));
  class trtn(ref="2");
  model response(event="1") = trtn age / dist=binomial link=logit;
  estimate "Adjusted Odds Ratio" trtn 1 -1 / exp;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        adjusted = sas.get_dataset("WORK", "ADJUSTED")
        self.assertEqual(adjusted["LABEL"].tolist(), ["Adjusted Odds Ratio"])
        self.assertTrue(math.isfinite(adjusted["LBETAESTIMATE"].iloc[0]))
        self.assertGreater(adjusted["EXPESTIMATE"].iloc[0], 0.0)

    def test_reports_unsupported_distribution(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data counts;
  input response exposure;
  datalines;
1 1
2 2
;
run;
proc genmod data=counts;
  model response = exposure / dist=poisson link=log;
run;
"""
        )

        self.assertFalse(result.success)
        errors = [step.error for step in result.steps if step.error]
        self.assertTrue(any("DIST=BINOMIAL" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
