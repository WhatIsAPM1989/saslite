import math
import unittest

from saslite import SasInterpreter


class ProcOdsContractTests(unittest.TestCase):
    def test_report_and_tabulate_publish_named_ods_objects(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data sales;
  input region $ amount;
  datalines;
East 10
East 20
West 5
;
run;
ods output Report=report_table;
proc report data=sales;
  column region amount;
  define region / group;
  define amount / analysis sum;
run;
ods output Table=tabulate_table;
proc tabulate data=sales;
  class region;
  var amount;
  table region*amount*sum;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        report = sas.get_dataset("WORK", "REPORT_TABLE")
        self.assertEqual(report["REGION"].tolist(), ["East", "West"])
        self.assertEqual(report["AMOUNT"].tolist(), [30.0, 5.0])
        tabulate = sas.get_dataset("WORK", "TABULATE_TABLE")
        self.assertEqual(tabulate["REGION"].tolist(), ["East", "West"])
        self.assertEqual(tabulate["AMOUNT_Sum"].tolist(), [30.0, 5.0])

    def test_report_across_rbreak_and_tabulate_dimensions(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data sales;
  input region $ quarter $ amount;
  datalines;
East Q1 10
East Q2 20
West Q1 5
West Q2 7
;
run;
ods output Report=across_report;
proc report data=sales;
  column region quarter amount;
  define region / group;
  define quarter / across;
  define amount / analysis sum;
run;
ods output Report=total_report;
proc report data=sales;
  column region amount;
  define region / group;
  define amount / analysis sum;
  rbreak after / summarize;
run;
ods output Table=dimension_table;
proc tabulate data=sales;
  class region;
  var amount;
  table region all, amount*(sum mean);
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        across = sas.get_dataset("WORK", "ACROSS_REPORT")
        self.assertEqual(across["REGION"].tolist(), ["East", "West"])
        self.assertEqual(across["AMOUNT_Q1"].tolist(), [10.0, 5.0])
        self.assertEqual(across["AMOUNT_Q2"].tolist(), [20.0, 7.0])
        total = sas.get_dataset("WORK", "TOTAL_REPORT")
        self.assertEqual(total["REGION"].tolist(), ["East", "West", "Total"])
        self.assertEqual(total["AMOUNT"].tolist(), [30.0, 12.0, 42.0])
        tabulate = sas.get_dataset("WORK", "DIMENSION_TABLE")
        self.assertEqual(tabulate["REGION"].tolist(), ["East", "West", "All"])
        self.assertEqual(tabulate["AMOUNT_Sum"].tolist(), [30.0, 12.0, 42.0])

    def test_freq_common_ods_tables_and_statistics(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data survey;
  input treatment response;
  datalines;
1 1
1 1
1 1
1 0
2 1
2 0
2 0
2 0
;
run;
ods output OneWayFreqs=oneway CrossTabFreqs=cross
           ChiSq=chisq FishersExact=fisher Measures=measures NLevels=levels;
proc freq data=survey;
  tables treatment treatment*response / chisq fisher measures;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        one_way = sas.get_dataset("WORK", "ONEWAY")
        self.assertEqual(one_way["Frequency"].tolist(), [4, 4])
        self.assertEqual(one_way["CumPercent"].tolist(), [50.0, 100.0])
        cross = sas.get_dataset("WORK", "CROSS")
        self.assertEqual(float(cross["Frequency"].sum()), 8.0)
        chisq = sas.get_dataset("WORK", "CHISQ")
        pearson = chisq[chisq["Statistic"] == "Chi-Square"].iloc[-1]
        self.assertAlmostEqual(pearson["Value"], 2.0, places=10)
        fisher = sas.get_dataset("WORK", "FISHER")
        self.assertAlmostEqual(fisher.iloc[0]["nValue1"], 0.48571428571428565)
        measures = sas.get_dataset("WORK", "MEASURES")
        self.assertAlmostEqual(measures.iloc[0]["Value"], 1 / 9)
        levels = sas.get_dataset("WORK", "LEVELS")
        self.assertTrue({"TableVar", "NLevels", "NMissLevels", "NNonMissLevels"}.issubset(levels.columns))

    def test_logistic_default_model_ods_contract(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data binary;
  input y x;
  datalines;
0 0
0 1
0 2
1 1
1 2
1 3
;
run;
ods output ModelInfo=model_info NObs=nobs ResponseProfile=response
           ConvergenceStatus=convergence FitStatistics=fit
           GlobalTests=global ParameterEstimates=parameters
           OddsRatios=odds Association=association;
proc logistic data=binary descending;
  model y=x;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        parameters = sas.get_dataset("WORK", "PARAMETERS")
        self.assertEqual(parameters["VARIABLE"].tolist(), ["Intercept", "X"])
        self.assertAlmostEqual(parameters["ESTIMATE"].iloc[1], math.log(4), places=5)
        fit = sas.get_dataset("WORK", "FIT")
        self.assertEqual(fit["CRITERION"].tolist(), ["AIC", "SC", "-2 Log L"])
        global_tests = sas.get_dataset("WORK", "GLOBAL")
        self.assertGreater(global_tests["CHISQ"].iloc[0], 0)
        association = sas.get_dataset("WORK", "ASSOCIATION")
        c_value = association.loc[association["LABEL"] == "c", "VALUE"].iloc[0]
        self.assertAlmostEqual(c_value, 7 / 9)
        for name in ("MODEL_INFO", "NOBS", "RESPONSE", "CONVERGENCE", "ODDS"):
            self.assertGreaterEqual(len(sas.get_dataset("WORK", name)), 1)

    def test_phreg_default_model_ods_contract(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data survival;
  input x time censor;
  datalines;
0 1 0
1 2 0
0 3 1
1 4 0
0 5 0
1 6 1
;
run;
ods output ModelInfo=model_info NObs=nobs ConvergenceStatus=convergence
           FitStatistics=fit GlobalTests=global
           ParameterEstimates=parameters HazardRatios=hazards;
proc phreg data=survival;
  model time*censor(1)=x / ties=breslow;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        parameters = sas.get_dataset("WORK", "PARAMETERS")
        self.assertEqual(parameters["VARIABLE"].tolist(), ["X"])
        estimate = parameters["ESTIMATE"].iloc[0]
        self.assertTrue(math.isfinite(estimate))
        hazards = sas.get_dataset("WORK", "HAZARDS")
        self.assertAlmostEqual(hazards["HAZARDRATIO"].iloc[0], math.exp(estimate))
        global_tests = sas.get_dataset("WORK", "GLOBAL")
        self.assertGreaterEqual(global_tests["CHISQ"].iloc[0], 0)
        for name in ("MODEL_INFO", "NOBS", "CONVERGENCE", "FIT"):
            self.assertGreaterEqual(len(sas.get_dataset("WORK", name)), 1)

    def test_mixed_default_model_ods_contract(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data repeated;
  input subject trt visit change;
  datalines;
11 1 1 2.7
11 1 2 3.2
12 1 1 2.9
12 1 2 3.4
21 2 1 1.7
21 2 2 2.2
22 2 1 1.9
22 2 2 2.4
;
run;
ods output ModelInfo=model_info Dimensions=dimensions NObs=nobs
           IterHistory=history ConvergenceStatus=convergence
           CovParms=covariance FitStatistics=fit SolutionF=solution
           Tests3=tests LSMeans=means Diffs=diffs R=r RCorr=rcorr;
proc mixed data=repeated method=reml;
  class subject trt visit;
  model change=trt visit trt*visit / noint solution;
  repeated visit / subject=subject type=cs r rcorr;
  lsmeans trt / diff cl;
run;
ods output close;
"""
        )

        self.assertTrue(result.success, result.error)
        solution = sas.get_dataset("WORK", "SOLUTION")
        self.assertTrue({"EFFECT", "ESTIMATE", "STDERR", "DF", "TVALUE", "PROBT"}.issubset(solution.columns))
        tests = sas.get_dataset("WORK", "TESTS")
        self.assertEqual(tests["EFFECT"].tolist(), ["TRT", "VISIT", "TRT*VISIT"])
        means = sas.get_dataset("WORK", "MEANS")
        self.assertEqual(means["ESTIMATE"].round(8).tolist(), [3.05, 2.05])
        covariance = sas.get_dataset("WORK", "COVARIANCE")
        self.assertEqual(covariance["COVPARM"].tolist(), ["CS", "Residual"])
        for name in ("MODEL_INFO", "DIMENSIONS", "NOBS", "HISTORY", "CONVERGENCE", "FIT", "DIFFS", "R", "RCORR"):
            self.assertGreaterEqual(len(sas.get_dataset("WORK", name)), 1)


if __name__ == "__main__":
    unittest.main()
