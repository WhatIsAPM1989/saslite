import unittest

from saslite import SasInterpreter
from saslite.runtime.types import is_missing


class VolgaExpressionSyntaxTests(unittest.TestCase):
    def test_numeric_missing_literal_and_caret_not_operator(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data result;
  missing_value=.;
  present=^missing(1);
  absent=^missing(.);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertTrue(is_missing(frame["missing_value"].iloc[0]))
        self.assertTrue(frame["present"].iloc[0])
        self.assertFalse(frame["absent"].iloc[0])

    def test_sql_contains_and_not_contains(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data names;
  input name $;
  datalines;
STARTDTC
OTHERDTC
VALUE
;
run;
proc sql;
  create table selected as
  select name
  from names
  where upcase(name) contains "DTC"
    and upcase(name) not contains "OTHER";
quit;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(frame["NAME"].tolist(), ["STARTDTC"])

    def test_length_range_accepts_format_style_trailing_dot(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data result;
  length col0-col4 $200.;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        dataset = sas.session.get_dataset("WORK", "RESULT")
        self.assertEqual(dataset.metadata.logical_variable_names(), [
            "COL0", "COL1", "COL2", "COL3", "COL4",
        ])
        self.assertTrue(all(
            variable.length == 200
            for variable in dataset.metadata.variables.values()
        ))
        self.assertTrue(all(
            variable.dtype == "character"
            for variable in dataset.metadata.variables.values()
        ))

    def test_name_prefix_lists_work_in_keep_and_drop(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  col1=1;
  col2=2;
  other=3;
run;
data kept;
  set source(keep=col: other);
  keep col:;
run;
data dropped;
  set source(drop=col:);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            [str(name).upper() for name in sas.get_dataset("WORK", "KEPT").columns],
            ["COL1", "COL2"],
        )
        self.assertEqual(
            [str(name).upper() for name in sas.get_dataset("WORK", "DROPPED").columns],
            ["OTHER"],
        )


if __name__ == "__main__":
    unittest.main()
