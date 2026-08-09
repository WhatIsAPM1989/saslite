import unittest

from saslite import SasInterpreter


REPEATED_DATA = """
data repeated;
  input subject trt visit change;
  datalines;
11 1 1 2.7
11 1 2 3.2
12 1 1 2.9
12 1 2 3.4
13 1 1 3.1
13 1 2 3.6
14 1 1 3.3
14 1 2 3.8
21 2 1 1.7
21 2 2 2.2
22 2 1 1.9
22 2 2 2.4
23 2 1 2.1
23 2 2 2.6
24 2 1 2.3
24 2 2 2.8
31 3 1 0.7
31 3 2 1.2
32 3 1 0.9
32 3 2 1.4
33 3 1 1.1
33 3 2 1.6
34 3 1 1.3
34 3 2 1.8
;
run;
"""


class ProcMixedTests(unittest.TestCase):
    def test_repeated_lsmeans_diffs_and_duplicate_ods_targets(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            REPEATED_DATA
            + """
ods output ConvergenceStatus=convergence
           LSMeans=means
           Diffs=diff12(where=(trt=1 and _trt=2))
           Diffs=diff13(where=(trt=1 and _trt=3));
proc mixed data=repeated method=reml;
  class subject trt visit;
  model change = trt visit trt*visit / noint solution ddfm=kr;
  repeated visit / sub=subject type=cs r;
  lsmeans trt / diff cl;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        convergence = sas.get_dataset("WORK", "CONVERGENCE")
        self.assertEqual(convergence["STATUS"].tolist(), [0])
        means = sas.get_dataset("WORK", "MEANS")
        self.assertEqual(means["TRT"].tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(means["ESTIMATE"].round(8).tolist(), [3.25, 2.25, 1.25])
        diff12 = sas.get_dataset("WORK", "DIFF12")
        self.assertEqual(diff12["ESTIMATE"].round(8).tolist(), [1.0])
        diff13 = sas.get_dataset("WORK", "DIFF13")
        self.assertEqual(diff13["ESTIMATE"].round(8).tolist(), [2.0])
        self.assertIn("PROBT", diff13.columns)
        self.assertIn("LOWER", diff13.columns)
        self.assertIn("UPPER", diff13.columns)

    def test_covariance_structures_produce_convergence_status(self) -> None:
        for covariance_type in ("un", "toeph", "arh(1)", "toep", "ar(1)", "cs"):
            with self.subTest(covariance_type=covariance_type):
                sas = SasInterpreter()
                result = sas.execute(
                    REPEATED_DATA
                    + f"""
ods output ConvergenceStatus=convergence;
proc mixed data=repeated method=reml maxfunc=1000;
  class subject trt visit;
  model change = trt visit trt*visit / noint solution;
  repeated visit / sub=subject type={covariance_type} r;
run;
ods output close;
"""
                )

                self.assertTrue(result.success, result.error)
                convergence = sas.get_dataset("WORK", "CONVERGENCE")
                self.assertEqual(convergence["STATUS"].tolist(), [0])

    def test_reports_unsupported_covariance_structure(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            REPEATED_DATA
            + """
proc mixed data=repeated;
  class subject trt visit;
  model change = trt visit;
  repeated visit / sub=subject type=hf;
run;
"""
        )

        self.assertFalse(result.success)
        errors = [step.error for step in result.steps if step.error]
        self.assertTrue(any("covariance TYPE=" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
