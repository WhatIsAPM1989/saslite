import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.parser.program_parser import ProgramParser


class ProcMeansOutputNameTests(unittest.TestCase):
    def test_multiple_output_names_follow_var_order(self) -> None:
        for procedure in ("means", "summary"):
            for grouping in ("", "class group;", "by group;"):
                with self.subTest(procedure=procedure, grouping=grouping):
                    sas = SasInterpreter()
                    sas.reporter.configure(quiet=True)
                    sas.create_dataset("source", pd.DataFrame({
                        "group": [1, 1],
                        "first": [10.0, 20.0],
                        "second": [100.0, float("nan")],
                    }))
                    result = sas.execute(f"""
                        proc {procedure} data=source nway noprint;
                          {grouping}
                          var second first;
                          output out=stats n=nsecond nfirst
                            mean=msecond mfirst sum=ssecond sfirst
                            std=sdsecond sdfirst median=medsecond medfirst
                            min=minsecond minfirst max=maxsecond maxfirst;
                        run;
                    """)

                    self.assertTrue(result.success, result.error)
                    row = sas.get_dataset("WORK", "STATS").iloc[0]
                    expected = {
                        "NSECOND": 1, "NFIRST": 2,
                        "MSECOND": 100.0, "MFIRST": 15.0,
                        "SSECOND": 100.0, "SFIRST": 30.0,
                        "MEDSECOND": 100.0, "MEDFIRST": 15.0,
                        "MINSECOND": 100.0, "MINFIRST": 10.0,
                        "MAXSECOND": 100.0, "MAXFIRST": 20.0,
                    }
                    for name, value in expected.items():
                        self.assertEqual(row[name], value, name)
                    self.assertTrue(pd.isna(row["SDSECOND"]))
                    self.assertAlmostEqual(row["SDFIRST"], 50 ** 0.5)

    def test_single_output_name_is_for_first_analysis_variable(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({"first": [10], "second": [99]}))
        result = sas.execute("""
            proc means data=source noprint;
              var first second;
              output out=stats mean=average;
            run;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "STATS")["AVERAGE"].tolist(), [10.0])

    def test_implicit_numeric_variable_order_and_quantile_names(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({
            "label": ["A", "B", "C", "D"],
            "first": [10, 20, 30, 40], "second": [100, 200, 300, 400],
        }))
        result = sas.execute("""
            proc means data=source noprint;
              output out=stats p25=qfirst qsecond p75=tfirst tsecond;
            run;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "STATS").to_dict("records"), [{
            "QFIRST": 17.5, "QSECOND": 175.0,
            "TFIRST": 32.5, "TSECOND": 325.0,
        }])

    def test_statistic_keywords_can_be_output_names(self) -> None:
        program = ProgramParser().parse("""
            proc means data=source noprint;
              var first second;
              output out=stats n=mean n mean=std sum std=min max;
            run;
        """)
        output = next(statement for statement in program.steps[0].statements
                      if isinstance(statement, dict))
        self.assertEqual(output["stats"], {
            "N": ["MEAN", "N"], "MEAN": ["STD", "SUM"], "STD": ["MIN", "MAX"],
        })

    def test_missing_groups_keep_both_analysis_variables(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({
            "group": [1.0, float("nan"), float("nan")],
            "first": [10.0, 20.0, 30.0],
            "second": [100.0, 200.0, float("nan")],
        }))
        result = sas.execute("""
            proc means data=source nway noprint missing;
              class group;
              var first second;
              output out=stats n=nfirst nsecond mean=mfirst msecond;
            run;
        """)

        self.assertTrue(result.success, result.error)
        output = sas.get_dataset("WORK", "STATS")
        self.assertEqual(len(output), 2)
        row = output[output["group"].isna()].iloc[0]
        self.assertEqual(row["NFIRST"], 2)
        self.assertEqual(row["NSECOND"], 1)
        self.assertEqual(row["MFIRST"], 25.0)
        self.assertEqual(row["MSECOND"], 200.0)

    def test_empty_grouped_output_preserves_declared_columns_for_later_steps(self) -> None:
        sas = SasInterpreter()
        result = sas.execute("""
            data source;
              length group $10 first second 8;
              stop;
            run;
            proc means data=source nway noprint missing;
              class group;
              var first second;
              output out=stats(drop=nfirst nsecond) n=nfirst nsecond
                mean=mfirst msecond std=sdfirst sdsecond;
            run;
            proc sql;
              create table copied as select group, mfirst, msecond from stats;
            quit;
        """)

        self.assertTrue(result.success, result.error)
        output = sas.get_dataset("WORK", "STATS")
        self.assertTrue(output.empty)
        self.assertEqual(list(output.columns), [
            "group", "MFIRST", "MSECOND", "SDFIRST", "SDSECOND",
        ])
        self.assertTrue(pd.api.types.is_numeric_dtype(output["MFIRST"]))
        self.assertEqual(list(sas.get_dataset("WORK", "COPIED").columns), [
            "group", "MFIRST", "MSECOND",
        ])


if __name__ == "__main__":
    unittest.main()
