import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.parser.program_parser import ProgramParser


class ProcCompatibilityOptionTests(unittest.TestCase):
    def test_means_nway_outputs_only_observed_full_class_groups(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "analysis",
            pd.DataFrame(
                {
                    "trtn": [1, 1, 1, 2],
                    "region": ["EU", "EU", "US", "EU"],
                    "days": [10, 20, 30, 40],
                }
            ),
        )

        result = sas.execute(
            """
            proc means data=analysis nway noprint;
              class trtn region;
              var days;
              output out=stats n=days_n mean=days_mean;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "STATS").sort_values(["trtn", "region"])
        self.assertEqual(
            actual.to_dict("records"),
            [
                {"trtn": 1, "region": "EU", "DAYS_N": 2, "DAYS_MEAN": 15.0},
                {"trtn": 1, "region": "US", "DAYS_N": 1, "DAYS_MEAN": 30.0},
                {"trtn": 2, "region": "EU", "DAYS_N": 1, "DAYS_MEAN": 40.0},
            ],
        )

    def test_report_nowindows_is_normalized_to_nowd(self) -> None:
        program = ProgramParser().parse(
            """
            proc report data=final nowindows headline;
              column label value;
              define label / display;
              define value / display;
            run;
            """
        )

        report = program.steps[0]
        self.assertTrue(report.options["NOWD"])
        self.assertNotIn("NOWINDOWS", report.options)

    def test_means_q1_q3_and_output_p25_p75(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "analysis",
            pd.DataFrame({"trtn": [1, 1, 1, 1], "days": [10, 20, 30, 40]}),
        )

        result = sas.execute(
            """
            proc means data=analysis nway q1 q3 noprint;
              class trtn;
              var days;
              output out=stats p25=days_q1 p75=days_q3;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "STATS").iloc[0]
        self.assertEqual(actual["DAYS_Q1"], 17.5)
        self.assertEqual(actual["DAYS_Q3"], 32.5)

    def test_report_accepts_presentation_only_header_options(self) -> None:
        program = ProgramParser().parse(
            """
            proc report data=final nowindows headline spanrows missing split="~"
                        spacing=0
                        style(report)=[cellpadding=0.7pt width=100%]
                        style(header)=[cellpadding=0]
                        style(column)=[cellpadding=0];
              column label value;
              define label / order noprint;
              define value / display style(column)={width=20% just=c};
            run;
            """
        )

        options = program.steps[0].options
        self.assertTrue(options["SPANROWS"])
        self.assertTrue(options["MISSING"])
        self.assertEqual(options["SPLIT"], "~")
        self.assertEqual(options["SPACING"], 0)
        self.assertTrue(options["STYLE_REPORT"])
        label_define = next(
            statement for statement in program.steps[0].statements
            if statement.get("action") == "define" and statement["name"] == "LABEL"
        )
        self.assertIn("NOPRINT", label_define["attrs"])


if __name__ == "__main__":
    unittest.main()
