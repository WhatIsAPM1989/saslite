import tempfile
import unittest
from pathlib import Path

import pandas as pd

from saslite import SasInterpreter
from saslite.parser.program_parser import ProgramParser


class ProcReportDocumentTests(unittest.TestCase):
    def test_ods_destination_parameters_are_preserved(self) -> None:
        program = ProgramParser().parse(
            'ods rtf file="report.rtf" style=journal; ods listing close;'
        )

        self.assertEqual(
            program.steps[0].options,
            {
                "ACTION": "CONTROL",
                "DESTINATION": "RTF",
                "FILE": "report.rtf",
                "STYLE": "journal",
            },
        )
        self.assertEqual(program.steps[1].options["DESTINATION"], "LISTING")
        self.assertTrue(program.steps[1].options["CLOSE"])

    def test_report_writes_rtf_or_listing_for_active_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rtf_path = root / "first.rtf"
            listing_path = root / "second.lst"
            sas = SasInterpreter()
            sas.create_dataset(
                "final",
                pd.DataFrame(
                    {
                        "category": ["Alpha", "Бета"],
                        "value": [10, 20],
                    }
                ),
            )

            result = sas.execute(
                f'''
                ods rtf file="{rtf_path}";
                proc report data=final nowd;
                  column category value;
                  define category / display "Категория";
                  define value / display "Value";
                run;
                ods rtf close;

                ods listing file="{listing_path}";
                proc report data=final nowd;
                  column category value;
                run;
                ods listing close;
                '''
            )

            self.assertTrue(result.success, result.error)
            rtf = rtf_path.read_text(encoding="ascii")
            listing = listing_path.read_text(encoding="utf-8")
            self.assertTrue(rtf.startswith(r"{\rtf1"))
            self.assertTrue(rtf.endswith("}"))
            self.assertIn(r"\trowd", rtf)
            self.assertIn(r"\u1050?", rtf)  # Cyrillic K in the DEFINE label.
            self.assertIn("PROC REPORT: WORK.FINAL", listing)
            self.assertIn("Alpha", listing)
            self.assertNotIn(r"{\rtf1", listing)

    def test_report_resolves_filename_fileref_and_close_stops_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rtf_path = Path(tmp) / "fileref-output.rtf"
            sas = SasInterpreter()
            sas.create_dataset("first", pd.DataFrame({"value": [1]}))
            sas.create_dataset("second", pd.DataFrame({"value": [2]}))

            result = sas.execute(
                f'''
                filename reportout "{rtf_path}";
                ods rtf file=reportout;
                proc report data=first; column value; run;
                ods rtf close;
                proc report data=second; column value; run;
                '''
            )

            self.assertTrue(result.success, result.error)
            rtf = rtf_path.read_text(encoding="ascii")
            self.assertEqual(rtf.count("PROC REPORT:"), 1)
            self.assertIn("WORK.FIRST", rtf)
            self.assertNotIn("WORK.SECOND", rtf)

    def test_ods_rtf_requires_file(self) -> None:
        result = SasInterpreter().execute("ods rtf;")

        self.assertFalse(result.success)
        self.assertEqual(result.steps[0].error, "ODS RTF requires FILE=")


if __name__ == "__main__":
    unittest.main()
