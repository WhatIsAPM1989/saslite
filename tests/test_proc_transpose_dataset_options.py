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

    def test_output_keep_and_drop_accept_prefix_lists(self) -> None:
        for empty in (False, True):
            with self.subTest(empty=empty):
                sas = SasInterpreter()
                sas.reporter.configure(quiet=True)
                source = pd.DataFrame({
                    "GRPX1": [1, 1], "TERMVAR1": ["Count", "Count"],
                    "TRT": [1, 2], "VAL": ["10", "20"],
                })
                sas.create_dataset("source", source.iloc[:0] if empty else source)
                result = sas.execute("""
                    proc transpose data=source out=kept(keep=TERMVAR: GRPX: COL:) prefix=COL;
                      by GRPX1 TERMVAR1;
                      id TRT;
                      var VAL;
                    run;
                    proc transpose data=source out=dropped(drop=_NAME_: TERMVAR:) prefix=COL;
                      by GRPX1 TERMVAR1;
                      id TRT;
                      var VAL;
                    run;
                """)
                self.assertTrue(result.success, result.error)
                self.assertFalse([warning for step in result.steps for warning in step.warnings])
                cells = [] if empty else ["COL1", "COL2"]
                self.assertEqual(sas.get_dataset("WORK", "KEPT").columns.tolist(),
                                 ["GRPX1", "TERMVAR1"] + cells)
                self.assertEqual(sas.get_dataset("WORK", "DROPPED").columns.tolist(),
                                 ["GRPX1"] + cells)
                if not empty:
                    self.assertEqual(sas.get_dataset("WORK", "KEPT")[cells].iloc[0].tolist(), ["10", "20"])

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
