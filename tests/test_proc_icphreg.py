import math
import unittest

from saslite import SasInterpreter


class ProcIcphregTests(unittest.TestCase):
    def test_piecewise_exponential_exact_and_right_censored_likelihood(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data interval;
  input arm ltime rtime;
  datalines;
1 1 1
1 2 2
1 3 .
2 4 4
2 5 5
2 6 .
;
run;
ods output HazardRatios=hazards ParameterEstimates=parameters;
proc icphreg data=interval;
  class arm(ref="2");
  model (ltime,rtime) = arm / base=piecewise(ninterval=1);
  hazardratio arm / alpha=0.05 diff=ref;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        hazards = sas.get_dataset("WORK", "HAZARDS")
        # With a constant baseline, the two event rates are 2/6 and 2/15.
        self.assertAlmostEqual(hazards["HAZARDRATIO"].iloc[0], 2.5, places=6)
        parameters = sas.get_dataset("WORK", "PARAMETERS")
        self.assertAlmostEqual(parameters["ESTIMATE"].iloc[0], math.log(2.5), places=6)

    def test_interval_censoring_strata_and_where(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data interval;
  input region arm ltime rtime include;
  datalines;
1 1 0 2 1
1 1 2 4 1
1 2 3 6 1
1 2 5 . 1
2 1 1 3 1
2 1 3 5 1
2 2 4 7 1
2 2 6 . 1
2 2 1 2 0
;
run;
ods output HazardRatios=hazards;
proc icphreg data=interval(where=(include=1));
  class arm(ref="2");
  model (ltime,rtime) = arm / base=piecewise(ninterval=2);
  hazardratio arm / diff=ref;
  strata region;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        hazards = sas.get_dataset("WORK", "HAZARDS")
        self.assertEqual(len(hazards), 1)
        self.assertTrue(math.isfinite(hazards["HAZARDRATIO"].iloc[0]))

    def test_right_censored_model_uses_phreg_compatibility_path(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data survival;
  input arm time cnsr;
  datalines;
1 1 0
1 3 0
1 5 1
2 2 0
2 4 0
2 6 1
;
run;
ods output HazardRatios=hazards;
proc icphreg data=survival;
  class arm(ref="2");
  model time*cnsr(1) = arm / base=piecewise(ninterval=2);
  hazardratio arm / diff=ref;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(sas.get_dataset("WORK", "HAZARDS")), 1)


if __name__ == "__main__":
    unittest.main()
