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

    def test_numeric_and_multiple_id_values_form_sas_variable_names(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input symptom $ trt _name_ $ value;
  datalines;
A 1 pcnt 10
A 1 count 2
A 2 pcnt 20
A 2 count 4
;
run;

data numeric_source;
  input symptom $ trt value;
  datalines;
A 1 10
A 2 20
;
run;

proc transpose data=source out=wide;
  by symptom;
  id trt _name_;
  var value;
run;

proc transpose data=numeric_source out=numeric_ids;
  by symptom;
  id trt;
  var value;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        wide = sas.get_dataset("WORK", "WIDE")
        self.assertEqual(
            [column.upper() for column in wide.columns],
            ["SYMPTOM", "_NAME_", "_1PCNT", "_1COUNT", "_2PCNT", "_2COUNT"],
        )
        self.assertEqual(wide[["_1PCNT", "_1COUNT", "_2PCNT", "_2COUNT"]].iloc[0].tolist(), [10, 2, 20, 4])
        numeric_ids = sas.get_dataset("WORK", "NUMERIC_IDS")
        self.assertIn("_1", {column.upper() for column in numeric_ids.columns})
        self.assertIn("_2", {column.upper() for column in numeric_ids.columns})


if __name__ == "__main__":
    unittest.main()
