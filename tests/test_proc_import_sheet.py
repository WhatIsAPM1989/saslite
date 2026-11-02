import tempfile
import unittest
from pathlib import Path

import pandas as pd

from saslite import SasInterpreter


class ProcImportSheetTests(unittest.TestCase):
    def _workbook(self, root):
        path = Path(root) / "source.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"value": [-1], "label": ["first"]}).to_excel(
                writer, sheet_name="First", index=False
            )
            pd.DataFrame({
                "value": [999, 10, 20],
                "label": ["skip", "keep", "also_keep"],
            }).to_excel(writer, sheet_name="Selected data", index=False)
        return path

    def test_sheet_statement_selects_named_excel_worksheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._workbook(tmp)
            for dbms in ("xlsx", "excel"):
                with self.subTest(dbms=dbms):
                    sas = SasInterpreter()
                    result = sas.execute(f'''
                        proc import out=loaded dbms={dbms}
                            datafile="{path}" replace;
                            sheet="Selected data";
                            getnames=yes;
                        run;
                    ''')
                    self.assertTrue(result.success, result.error)
                    data = sas.get_dataset("WORK", "LOADED")
                    self.assertEqual(data["value"].tolist(), [999, 10, 20])
                    self.assertEqual(data["label"].tolist(), ["skip", "keep", "also_keep"])

    def test_sheet_with_getnames_yes_preserves_datarow_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._workbook(tmp)
            sas = SasInterpreter()
            result = sas.execute(f'''
                proc import out=loaded dbms=xlsx datafile="{path}" replace;
                    sheet='Selected data'; getnames=yes; datarow=3;
                run;
            ''')
            self.assertTrue(result.success, result.error)
            self.assertEqual(sas.get_dataset("WORK", "LOADED")["value"].tolist(), [10, 20])

    def test_sheet_with_getnames_no_preserves_header_as_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._workbook(tmp)
            sas = SasInterpreter()
            result = sas.execute(f'''
                proc import out=loaded dbms=xlsx datafile="{path}" replace;
                    sheet="Selected data"; getnames=no;
                run;
            ''')
            self.assertTrue(result.success, result.error)
            data = sas.get_dataset("WORK", "LOADED")
            self.assertEqual(data.iloc[:, 0].tolist(), ["value", 999, 10, 20])
            self.assertEqual(data.iloc[:, 1].tolist(), ["label", "skip", "keep", "also_keep"])

    def test_no_sheet_statement_keeps_first_sheet_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._workbook(tmp)
            sas = SasInterpreter()
            result = sas.execute(f'''
                proc import out=loaded dbms=xlsx datafile="{path}" replace;
                run;
            ''')
            self.assertTrue(result.success, result.error)
            self.assertEqual(sas.get_dataset("WORK", "LOADED")["value"].tolist(), [-1])

    def test_missing_sheet_reports_error_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._workbook(tmp)
            sas = SasInterpreter()
            self.assertTrue(sas.execute("data loaded; marker=7; run;").success)
            result = sas.execute(f'''
                proc import out=loaded dbms=xlsx datafile="{path}" replace;
                    sheet="Missing";
                run;
            ''')
            self.assertFalse(result.success)
            self.assertIn("Missing", result.steps[-1].error or "")
            self.assertEqual(sas.get_dataset("WORK", "LOADED")["marker"].tolist(), [7])


if __name__ == "__main__":
    unittest.main()
