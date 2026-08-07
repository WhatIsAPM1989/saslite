import unittest

from saslite import SasInterpreter


class SqlSchemaDiagnosticsTests(unittest.TestCase):
    def test_missing_select_variable_warns_and_materializes_missing_values(self) -> None:
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
proc sql;
  create table selected as
  select id, missing_select
  from source;
quit;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(frame["ID"].tolist(), [1, 2])
        self.assertEqual(frame["missing_select"].tolist(), [None, None])
        warnings = "\n".join(result.steps[-1].warnings)
        self.assertIn("MISSING_SELECT referenced by SELECT", warnings)
        self.assertIn("WORK.SOURCE", warnings)

    def test_missing_where_variable_warns_when_it_filters_every_row(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id;
  datalines;
1
2
;
run;
proc sql;
  select id from source where missing_where=1;
quit;
"""
        )

        self.assertTrue(result.success, result.error)
        warnings = "\n".join(result.steps[-1].warnings)
        self.assertIn("MISSING_WHERE referenced by WHERE", warnings)
        self.assertEqual(warnings.count("MISSING_WHERE referenced by WHERE"), 1)


if __name__ == "__main__":
    unittest.main()
