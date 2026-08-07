import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.runtime.dataset import Dataset


class ProcTransposeDatasetOptionTests(unittest.TestCase):
    def test_empty_input_preserves_by_and_transpose_metadata_schema(self) -> None:
        sas = SasInterpreter()
        empty = pd.DataFrame({
            "USUBJID": pd.Series(dtype="object"),
            "QNAM": pd.Series(dtype="object"),
            "QVAL": pd.Series(dtype="object"),
        })
        sas.session.put_dataset(
            "WORK",
            "EMPTY_LONG",
            Dataset.from_dataframe(empty, name="EMPTY_LONG"),
        )

        result = sas.execute(
            """
proc transpose data=empty_long out=empty_wide name=source label=source_label;
  by usubjid;
  id qnam;
  var qval;
run;

data copied_empty_wide;
  set empty_wide;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "EMPTY_WIDE")
        self.assertTrue(frame.empty)
        self.assertEqual(
            [column.upper() for column in frame.columns],
            ["USUBJID", "SOURCE", "SOURCE_LABEL"],
        )
        copied = sas.get_dataset("WORK", "COPIED_EMPTY_WIDE")
        self.assertTrue(copied.empty)
        self.assertEqual(
            [column.upper() for column in copied.columns],
            ["USUBJID", "SOURCE", "SOURCE_LABEL"],
        )

    def test_out_drop_name_option_is_applied(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data cycles0;
  input usubjid $ cycleid $ aval;
  datalines;
01 D_NEOADJ 4
01 T_NEOADJ 3
02 D_NEOADJ 2
;
run;

proc transpose data=cycles0 out=work.cycles1(drop=_name_);
  by usubjid;
  id cycleid;
  var aval;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "CYCLES1")
        self.assertEqual(
            [column.upper() for column in frame.columns],
            ["USUBJID", "D_NEOADJ", "T_NEOADJ"],
        )
        self.assertEqual(frame["USUBJID"].tolist(), ["01", "02"])
        self.assertEqual(frame["D_NEOADJ"].tolist(), [4, 2])


if __name__ == "__main__":
    unittest.main()
