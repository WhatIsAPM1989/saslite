import math
import unittest

import pandas as pd

from saslite import SasInterpreter


class DataStepMultiMergeTests(unittest.TestCase):
    def test_three_way_merge_overwrites_shared_variables_without_suffixes(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data first;
  input id shared first_only;
  datalines;
1 10 100
2 20 200
4 50 400
;
run;

data second;
  input id shared second_only;
  datalines;
1 . 1000
3 30 3000
4 . 4000
;
run;

data third;
  input id shared third_only;
  datalines;
1 40 10000
;
run;

data merged;
  merge first(in=in_first)
        second(in=in_second)
        third(in=in_third);
  by id;
  from_first=in_first;
  from_second=in_second;
  from_third=in_third;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "MERGED")
        self.assertEqual(frame["ID"].tolist(), [1, 2, 3, 4])
        self.assertEqual(frame.loc[frame["ID"] == 1, "SHARED"].iloc[0], 40)
        self.assertEqual(frame.loc[frame["ID"] == 2, "SHARED"].iloc[0], 20)
        self.assertEqual(frame.loc[frame["ID"] == 3, "SHARED"].iloc[0], 30)
        self.assertTrue(math.isnan(frame.loc[frame["ID"] == 4, "SHARED"].iloc[0]))
        self.assertFalse(any(str(column).endswith(("_x", "_y")) for column in frame))
        self.assertEqual(
            frame[["from_first", "from_second", "from_third"]].values.tolist(),
            [[1, 1, 1], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        )

    def test_empty_merge_uses_descriptors_without_comparing_pandas_key_types(self) -> None:
        sas = SasInterpreter()
        sas.reporter.configure(quiet=True)
        sas.create_dataset("first", pd.DataFrame({
            "ID": pd.Series(dtype="object"), "left_value": pd.Series(dtype="float64"),
        }))
        # Empty pandas storage can be object despite a numeric SAS descriptor.
        sas.session.get_dataset("WORK", "FIRST").metadata.get_variable("ID").dtype = "numeric"
        sas.create_dataset("second", pd.DataFrame({
            "ID": pd.Series(dtype="float64"), "right_value": pd.Series(dtype="float64"),
        }))
        result = sas.execute("""
            data merged;
              merge first(in=left) second(in=right);
              by ID;
            run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertFalse([warning for step in result.steps for warning in step.warnings])
        output = sas.session.get_dataset("WORK", "MERGED")
        self.assertEqual(output.data.shape, (0, 3))
        self.assertEqual(output.data.columns.tolist(), ["ID", "left_value", "right_value"])
        self.assertEqual(output.metadata.get_variable("ID").dtype, "numeric")

    def test_shorter_input_retains_last_row_within_by_group(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data longer;
  input id visit left_value shared;
  datalines;
1 1 10 100
1 2 20 200
;
run;

data shorter;
  input id right_value shared;
  datalines;
1 90 900
;
run;

data combined;
  merge longer shorter(in=in_shorter);
  by id;
  shorter_present=in_shorter;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "COMBINED")
        self.assertEqual(frame["VISIT"].tolist(), [1, 2])
        self.assertEqual(frame["RIGHT_VALUE"].tolist(), [90, 90])
        self.assertEqual(frame["SHARED"].tolist(), [900, 900])
        self.assertEqual(frame["shorter_present"].tolist(), [1, 1])


if __name__ == "__main__":
    unittest.main()
