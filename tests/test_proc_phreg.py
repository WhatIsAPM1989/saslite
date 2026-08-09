import math
import unittest

from saslite import SasInterpreter


class ProcPhregTests(unittest.TestCase):
    def test_binary_class_effect_and_ods_outputs(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  input arm time cnsr;
  datalines;
1 1 0
1 4 0
1 7 1
1 9 0
2 2 0
2 3 1
2 6 0
2 10 0
;
run;
ods output HazardRatios=hazard_ratios ParameterEstimates=parameters;
proc phreg data=adtte;
  class arm(ref="2");
  model time*cnsr(1)=arm / ties=efron;
  hazardratio arm / cl=pl diff=ref;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        hazard = sas.get_dataset("WORK", "HAZARD_RATIOS")
        self.assertEqual(len(hazard), 1)
        self.assertEqual(hazard["DESCRIPTION"].iloc[0], "ARM 1 vs 2")
        # Independent score-equation solution for this no-ties fixture:
        # beta=0.3871260935, exp(beta)=1.4727421828.
        self.assertAlmostEqual(hazard["HAZARDRATIO"].iloc[0], 1.4727421828, places=6)
        self.assertLess(hazard["PLLOWER"].iloc[0], hazard["HAZARDRATIO"].iloc[0])
        self.assertGreater(hazard["PLUPPER"].iloc[0], hazard["HAZARDRATIO"].iloc[0])
        parameters = sas.get_dataset("WORK", "PARAMETERS")
        self.assertEqual(parameters["PARAMETER"].tolist(), ["ARM"])
        self.assertAlmostEqual(parameters["ESTIMATE"].iloc[0], 0.3871260935, places=6)
        self.assertTrue(math.isfinite(parameters["PROBCHISQ"].iloc[0]))

    def test_numeric_covariate_where_and_strata(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  input region age time cnsr include;
  datalines;
1 30 2 0 1
1 40 5 0 1
1 50 7 1 1
2 35 1 0 1
2 45 6 0 1
2 55 8 1 1
2 60 9 0 0
;
run;
ods output ParameterEstimates=parameters;
proc phreg data=adtte(where=(include=1));
  model time*cnsr(1)=age / ties=efron;
  strata region;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        parameters = sas.get_dataset("WORK", "PARAMETERS")
        self.assertEqual(parameters["VARIABLE"].tolist(), ["AGE"])
        self.assertTrue(math.isfinite(parameters["ESTIMATE"].iloc[0]))

    def test_requires_events(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adtte;
  input arm time cnsr;
  datalines;
1 1 1
2 2 1
;
run;
proc phreg data=adtte;
  class arm(ref="2");
  model time*cnsr(1)=arm;
run;
"""
        )

        self.assertFalse(result.success)
        errors = [step.error for step in result.steps if step.error]
        self.assertTrue(any("no events" in error.lower() for error in errors))


if __name__ == "__main__":
    unittest.main()
