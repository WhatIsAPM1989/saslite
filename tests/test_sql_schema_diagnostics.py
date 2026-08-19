import unittest

from saslite import SasInterpreter


class SqlSchemaDiagnosticsTests(unittest.TestCase):
    def test_grouped_query_remerges_selected_detail_columns(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id grp detail $ value;
  datalines;
1 1 A 10
1 1 B 20
2 1 C 5
;
run;
proc sql;
  create table selected as
  select id, grp, detail, max(value) as max_value
  from source
  group by id, grp;
quit;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(
            [str(column).upper() for column in frame.columns],
            ["ID", "GRP", "DETAIL", "MAX_VALUE"],
        )
        self.assertEqual(frame["detail"].tolist(), ["A", "B", "C"])
        self.assertEqual(frame["max_value"].tolist(), [20, 20, 5])

    def test_missing_select_variable_in_generated_work_warns_and_materializes(self) -> None:
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
        self.assertIn("MISSING_SELECT", warnings)
        self.assertIn("WORK.SOURCE", warnings)
        self.assertFalse(sas.session.schema_expectations)

    def test_missing_where_variable_in_generated_work_warns_once(self) -> None:
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
        self.assertIn("MISSING_WHERE", warnings)
        self.assertIn("WORK.SOURCE", warnings)
        self.assertEqual(warnings.count("MISSING_WHERE"), 1)
        self.assertFalse(sas.session.schema_expectations)


if __name__ == "__main__":
    unittest.main()
