import math
import unittest

from saslite import SasInterpreter


class DataStepInOptionTests(unittest.TestCase):
    def test_nested_iterative_do_loops_preserve_inner_output_block(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
            data trt_shell;
              length trt01a $20 type $4;
              do trt01an=1 to 3;
                if trt01an=1 then trt01a="D+T+EV";
                else if trt01an=2 then trt01a="D+EV";
                else trt01a="SoC";
                do typeord=1 to 2;
                  if typeord=1 then type="AEOT";
                  else type="IMAE";
                  output;
                end;
              end;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "TRT_SHELL")
        self.assertEqual(len(actual), 6)
        self.assertEqual(
            actual[["trt01an", "typeord", "type"]].to_dict("records"),
            [
                {"trt01an": 1, "typeord": 1, "type": "AEOT"},
                {"trt01an": 1, "typeord": 2, "type": "IMAE"},
                {"trt01an": 2, "typeord": 1, "type": "AEOT"},
                {"trt01an": 2, "typeord": 2, "type": "IMAE"},
                {"trt01an": 3, "typeord": 1, "type": "AEOT"},
                {"trt01an": 3, "typeord": 2, "type": "IMAE"},
            ],
        )

    def test_numbered_variable_lists_expand_in_length_and_keep(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data expanded;
  length col1-col3 $20;
  col1="a";
  col2="b";
  col3="c";
  keep col1-col3;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "EXPANDED")
        self.assertEqual(list(frame.columns), ["col1", "col2", "col3"])
        self.assertEqual(frame.iloc[0].tolist(), ["a", "b", "c"])

    def test_input_accepts_double_question_mark_informat_modifier(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            'data parsed; valid=input("2024-01-01", ?? yymmdd10.); '
            'invalid=input("not-a-date", ?? yymmdd10.); run;'
        )

        self.assertTrue(result.success, result.error)
        row = sas.get_dataset("WORK", "PARSED").iloc[0]
        self.assertEqual(row["valid"], 23376.0)
        self.assertTrue(math.isnan(row["invalid"]))

    def test_merge_in_flag_filters_master_rows_and_is_not_output(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data master;
  input id x;
  datalines;
1 10
2 20
;
run;

data detail;
  input id y;
  datalines;
2 200
3 300
;
run;

data wanted;
  merge master(in=in_master) detail(in=in_detail);
  by id;
  if in_master;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "WANTED")
        self.assertEqual(frame["ID"].tolist(), [1.0, 2.0])
        self.assertEqual([column.upper() for column in frame.columns], ["ID", "X", "Y"])

    def test_set_in_flag_identifies_contributing_dataset(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data first;
  input id;
  datalines;
1
2
;
run;

data second;
  input id;
  datalines;
3
;
run;

data from_first;
  set first(in=in_first) second(in=in_second);
  if in_first;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "FROM_FIRST")
        self.assertEqual(frame["ID"].tolist(), [1, 2])
        self.assertEqual([column.upper() for column in frame.columns], ["ID"])

    def test_subsetting_if_does_not_capture_following_statements(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id selected;
  datalines;
1 1
2 0
;
run;

data wanted;
  set source;
  if selected;
  first_value=id;
  second_value=id+10;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "WANTED")
        self.assertEqual(frame["ID"].tolist(), [1])
        self.assertEqual(frame["first_value"].tolist(), [1])
        self.assertEqual(frame["second_value"].tolist(), [11])


if __name__ == "__main__":
    unittest.main()
