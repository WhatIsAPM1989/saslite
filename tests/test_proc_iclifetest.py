import unittest

from saslite import SasInterpreter


class ProcIclifetestTests(unittest.TestCase):
    def test_turnbull_outputs_by_group_quartiles_and_survival(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data intervals;
  input trt ltime rtime;
  datalines;
1 1 1
1 2 2
1 3 3
1 4 4
2 0 2
2 2 4
2 4 .
;
run;
ods output Quartiles=quartiles SurvivalPlot=survival;
proc iclifetest data=intervals alpha=0.05 method=emicm
                conftype=loglog impute(seed=12345) plots=survival;
  time (ltime,rtime);
  by trt;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        quartiles = sas.get_dataset("WORK", "QUARTILES")
        first_group = quartiles[quartiles["TRT"] == 1]
        median = first_group[first_group["PERCENT"] == 50]
        self.assertEqual(median["ESTIMATE"].tolist(), [2.0])
        survival = sas.get_dataset("WORK", "SURVIVAL")
        first_curve = survival[survival["TRT"] == 1]
        self.assertEqual(
            first_curve["SURVIVAL"].round(8).tolist(),
            [1.0, 0.75, 0.5, 0.25, 0.0],
        )

    def test_where_and_ods_dataset_options(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data intervals;
  input ltime rtime include;
  datalines;
1 1 1
2 2 1
3 3 1
9 9 0
;
run;
ods output Quartiles=median(where=(percent=50));
proc iclifetest data=intervals(where=(include=1));
  time (ltime,rtime);
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        median = sas.get_dataset("WORK", "MEDIAN")
        self.assertEqual(median["ESTIMATE"].tolist(), [2.0])


if __name__ == "__main__":
    unittest.main()
