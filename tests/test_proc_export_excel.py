import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from saslite import SasInterpreter


class ProcExportDatasetOptionTests(unittest.TestCase):
    def test_data_options_are_applied_before_csv_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "filtered.csv"
            source = f"""
data source;
  input id group $ value extra;
  datalines;
1 A 10 100
2 B 20 200
3 A 30 300
;
run;

proc export
  data=source(
    keep=id group value extra
    where=(group="A")
    rename=(value=amount)
    drop=group extra
  )
  outfile="{output}"
  dbms=csv
  replace;
run;
"""

            result = SasInterpreter().execute(source)

            self.assertTrue(result.success, result.error)
            frame = pd.read_csv(output)
            self.assertEqual(
                frame.to_dict("records"),
                [{"ID": 1, "amount": 10}, {"ID": 3, "amount": 30}],
            )


@unittest.skipUnless(
    importlib.util.find_spec("openpyxl") is not None,
    "openpyxl is installed through the optional excel extra",
)
class ProcExportExcelTests(unittest.TestCase):
    def test_xlsx_export_honors_sheet_labels_and_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.xlsx"
            source = f"""
data source;
  length code $3;
  input code $ amount;
  label code="Subject code" amount="Amount";
  datalines;
A01 10
A02 20
;
run;

proc export
  data=source
  outfile="{output}"
  dbms=xlsx
  label
  replace;
  sheet="Results";
run;
"""

            result = SasInterpreter().execute(source)

            self.assertTrue(result.success, result.error)
            frame = pd.read_excel(output, sheet_name="Results")
            self.assertEqual(list(frame.columns), ["Subject code", "Amount"])
            self.assertEqual(frame.to_dict("records"), [
                {"Subject code": "A01", "Amount": 10},
                {"Subject code": "A02", "Amount": 20},
            ])


if __name__ == "__main__":
    unittest.main()
