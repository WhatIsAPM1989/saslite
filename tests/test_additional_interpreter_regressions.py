import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class AdditionalInterpreterRegressionTests(unittest.TestCase):
    def test_lowercase_substr_assignment_updates_its_target(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data patched;
  length code $8;
  code='ABCDEFGH';
  substr(code, 3, 2)='--';
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "PATCHED")
        self.assertEqual(frame["code"].tolist(), ["AB--EFGH"])
        self.assertNotIn("SUBSTR", {str(column).upper() for column in frame.columns})
        self.assertFalse(result.steps[-1].warnings)

    def test_substr_assignment_without_length_replaces_source_characters(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data patched;
  length code $8;
  code='ABCDEFGH';
  substr(code, 3)='--';
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "PATCHED")
        self.assertEqual(frame["code"].tolist(), ["AB--EFGH"])

    def test_proc_append_matches_variable_names_case_insensitively(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data base;
  input id code $;
  datalines;
1 A
2 B
;
run;

data extra;
  id=3;
  code='C';
run;

proc append base=base data=extra;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "BASE")
        self.assertEqual(frame["ID"].tolist(), [1, 2, 3])
        self.assertEqual(frame["CODE"].tolist(), ["A", "B", "C"])

    def test_array_assignment_marks_elements_as_initialized(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data matrix;
  array values[3] v1 v2 v3;
  do id=1 to 3;
    do i=1 to 3;
      values[i]=id*i;
    end;
    total=sum(of values[*]);
    output;
  end;
  drop i;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "MATRIX")
        self.assertEqual(frame["total"].tolist(), [6, 12, 18])
        self.assertFalse(result.steps[-1].warnings)

    def test_literal_array_assignment_does_not_hide_uninitialized_elements(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data result;
  array values[2] v1 v2;
  values[1]=1;
  total=sum(of values[*]);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        warnings = result.steps[-1].warnings
        self.assertFalse(any("V1 is uninitialized" in warning for warning in warnings))
        self.assertTrue(any("V2 is uninitialized" in warning for warning in warnings))

    def test_curly_braces_are_accepted_for_array_subscripts(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data result;
  array vars {5} _0 _1 _2 _3 _4;
  _0=.; _1=1; _2=.; _3=3; _4=.;
  do i=1 to 5;
    if vars {i}=. then vars{i}=0;
  end;
  total=sum(of vars{*});
  drop i;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(frame[["_0", "_1", "_2", "_3", "_4"]].iloc[0].tolist(), [0, 1, 0, 3, 0])
        self.assertEqual(frame["total"].tolist(), [4])

    def test_put_named_variable_writes_name_and_value(self) -> None:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)

        result = sas.execute(
            'data result; att="Other"; put "WARNING: Unknown attribute " att=; run;'
        )

        self.assertTrue(result.success, result.error)
        self.assertIn("WARNING: Unknown attribute  att=Other", log.getvalue())

    def test_sysnobs_is_available_to_macro_flow_after_a_step(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            """
data source;
  value=1;
  output;
  value=2;
  output;
run;

%if &sysnobs=2 %then %do;
  data selected;
    matched=1;
  run;
%end;
%else %do;
  data selected;
    matched=0;
  run;
%end;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "SELECTED")["matched"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
