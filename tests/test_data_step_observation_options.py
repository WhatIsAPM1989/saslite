import unittest

from saslite import SasInterpreter


class DataStepObservationOptionTests(unittest.TestCase):
    def test_set_firstobs_and_obs_are_one_based_and_inclusive(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id value unused;
  datalines;
1 10 100
2 20 200
3 30 300
4 40 400
5 50 500
;
run;

data selected;
  set source(firstobs=2 obs=4 keep=id value rename=(value=amount) in=chosen);
  was_chosen=chosen;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(frame["ID"].tolist(), [2, 3, 4])
        self.assertEqual(frame["amount"].tolist(), [20, 30, 40])
        self.assertEqual(frame["was_chosen"].tolist(), [1, 1, 1])
        self.assertNotIn("UNUSED", frame.columns)
        self.assertNotIn("CHOSEN", [str(column).upper() for column in frame.columns])

    def test_merge_slices_each_input_before_matching_by_values(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data left_side;
  input id left_value;
  datalines;
1 10
2 20
3 30
4 40
;
run;

data right_side;
  input id right_value;
  datalines;
1 100
2 200
3 300
4 400
;
run;

data combined;
  merge left_side(firstobs=2 obs=3 in=in_left)
        right_side(firstobs=3 obs=4 in=in_right);
  by id;
  from_left=in_left;
  from_right=in_right;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "COMBINED")
        self.assertEqual(frame["ID"].tolist(), [2, 3, 4])
        self.assertEqual(
            frame[["from_left", "from_right"]].values.tolist(),
            [[1, 0], [1, 1], [0, 1]],
        )

    def test_obs_zero_produces_a_zero_observation_set_input(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id value;
  datalines;
1 10
2 20
;
run;

data empty;
  set source(obs=0);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "EMPTY")
        self.assertEqual(len(frame), 0)
        self.assertEqual([str(column).upper() for column in frame.columns], ["ID", "VALUE"])

    def test_output_dataset_keep_drop_and_rename_options(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data selected(keep=id value unused drop=unused rename=(value=amount));
  id=1;
  value=10;
  unused=100;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(
            [str(column).upper() for column in frame.columns],
            ["ID", "AMOUNT"],
        )
        self.assertEqual(frame["amount"].tolist(), [10])

    def test_input_where_option_filters_before_keep_and_drop(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id group value;
  datalines;
1 1 10
2 2 20
3 1 30
;
run;
data selected;
  set source(where=(group=1) keep=id group value drop=group);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(frame["ID"].tolist(), [1, 3])
        self.assertEqual(frame["VALUE"].tolist(), [10, 30])
        self.assertNotIn("GROUP", frame.columns)

    def test_output_where_option_filters_before_column_options(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id value;
  datalines;
1 10
2 20
3 30
;
run;
data selected(where=(value>=20) keep=id value rename=(value=amount));
  set source;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(frame["ID"].tolist(), [2, 3])
        self.assertEqual(frame["amount"].tolist(), [20, 30])


if __name__ == "__main__":
    unittest.main()
