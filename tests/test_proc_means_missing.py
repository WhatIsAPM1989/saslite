import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.parser.program_parser import ProgramParser


class ProcMeansMissingTests(unittest.TestCase):
    def test_means_and_summary_parse_missing_flag(self) -> None:
        for procedure in ("means", "summary"):
            with self.subTest(procedure=procedure):
                program = ProgramParser().parse(
                    f"proc {procedure} data=source nway noprint MiSsInG; "
                    "class group; var value; run;"
                )
                self.assertTrue(program.steps[0].options["MISSING"])

    def test_missing_class_groups_match_in_listing_and_both_outputs(self) -> None:
        for procedure in ("means", "summary"):
            for missing in (False, True):
                with self.subTest(procedure=procedure, missing=missing):
                    sas = SasInterpreter()
                    sas.reporter.configure(quiet=True)
                    source = pd.DataFrame({
                        "group": [1.0, 1.0, float("nan"), float("nan")],
                        "value": [10.0, 20.0, 777.0, float("nan")],
                    })
                    sas.create_dataset("source", source)
                    result = sas.execute(f"""
                        proc {procedure} data=source out=legacy nway n mean
                            {'missing' if missing else ''};
                          class group;
                          var value;
                          output out=stats n=count mean=average;
                        run;
                    """)

                    self.assertTrue(result.success, result.error)
                    output = sas.get_dataset("WORK", "STATS")
                    legacy = sas.get_dataset("WORK", "LEGACY")
                    self.assertEqual(len(output), 2 if missing else 1)
                    self.assertEqual(len(legacy), len(output))
                    observed = output[output["group"].notna()].iloc[0]
                    self.assertEqual(observed["COUNT"], 2)
                    self.assertEqual(observed["AVERAGE"], 15.0)
                    listing = "\n".join(result.steps[-1].output_messages)
                    self.assertEqual("777" in listing, missing)
                    if missing:
                        absent = output[output["group"].isna()].iloc[0]
                        self.assertEqual(absent["COUNT"], 1)
                        self.assertEqual(absent["AVERAGE"], 777.0)
                    pd.testing.assert_frame_equal(
                        sas.get_dataset("WORK", "SOURCE"), source,
                    )

    def test_blank_and_null_character_class_values_form_one_missing_group(self) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing):
                sas = SasInterpreter()
                sas.create_dataset("source", pd.DataFrame({
                    "group": ["A", "", "   ", None],
                    "value": [10, 20, 30, 40],
                }))
                result = sas.execute(f"""
                    proc means data=source nway noprint {'missing' if missing else ''};
                      class group;
                      var value;
                      output out=stats n=count sum=total;
                    run;
                """)

                self.assertTrue(result.success, result.error)
                output = sas.get_dataset("WORK", "STATS")
                self.assertEqual(len(output), 2 if missing else 1)
                self.assertEqual(output["TOTAL"].sum(), 100 if missing else 10)
                if missing:
                    absent = output[output["group"].isna()].iloc[0]
                    self.assertEqual(absent["COUNT"], 3)
                    self.assertEqual(absent["TOTAL"], 90)

    def test_missing_in_any_class_variable_controls_inclusion(self) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing):
                sas = SasInterpreter()
                sas.create_dataset("source", pd.DataFrame({
                    "treatment": [1.0, 1.0, float("nan"), float("nan")],
                    "region": ["EU", "", "EU", ""],
                    "value": [10, 20, 30, 40],
                }))
                result = sas.execute(f"""
                    proc means data=source nway noprint {'missing' if missing else ''};
                      class treatment region;
                      var value;
                      output out=stats sum=total;
                    run;
                """)

                self.assertTrue(result.success, result.error)
                output = sas.get_dataset("WORK", "STATS")
                self.assertEqual(len(output), 4 if missing else 1)
                self.assertEqual(output["TOTAL"].sum(), 100 if missing else 10)

    def test_by_missing_groups_are_included_without_missing_option(self) -> None:
        sas = SasInterpreter()
        sas.reporter.configure(quiet=True)
        sas.create_dataset("source", pd.DataFrame({
            "group": [float("nan"), 1.0], "value": [777, 10],
        }))
        result = sas.execute("""
            proc means data=source n mean;
              by group;
              var value;
              output out=stats mean=average;
            run;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(sas.get_dataset("WORK", "STATS")), 2)
        self.assertIn("777", "\n".join(result.steps[-1].output_messages))

    def test_missing_does_not_count_missing_analysis_values(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({"value": [10.0, float("nan")]}))
        result = sas.execute("""
            proc means data=source missing noprint;
              var value;
              output out=stats n=count mean=average;
            run;
        """)

        self.assertTrue(result.success, result.error)
        output = sas.get_dataset("WORK", "STATS").iloc[0]
        self.assertEqual(output["COUNT"], 1)
        self.assertEqual(output["AVERAGE"], 10.0)

    def test_missing_accepts_empty_input(self) -> None:
        sas = SasInterpreter()
        result = sas.execute("""
            data source;
              length group $10 value 8;
              stop;
            run;
            proc means data=source nway noprint missing;
              class group;
              var value;
              output out=stats n=count mean=average;
            run;
        """)

        self.assertTrue(result.success, result.error)
        self.assertTrue(sas.get_dataset("WORK", "STATS").empty)


if __name__ == "__main__":
    unittest.main()
