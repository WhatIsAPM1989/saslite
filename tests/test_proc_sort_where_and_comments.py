import unittest

from saslite import SasInterpreter
from saslite.macro.expander import MacroExpander


class ProcSortWhereTests(unittest.TestCase):
    def test_where_statement_filters_before_sorting(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length group $1;
  id=3; group='A'; output;
  id=1; group='A'; output;
  id=2; group='B'; output;
run;
proc sort data=source out=selected;
  where group='A';
  by id;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        selected = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(selected["id"].tolist(), [1, 3])
        self.assertEqual(selected["group"].tolist(), ["A", "A"])
        metadata = sas.session.get_dataset("WORK", "SELECTED").metadata
        self.assertEqual(metadata.row_count, 2)
        self.assertEqual(metadata.sort_keys, ["id"])

    def test_where_statement_is_accepted_after_by(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  id=2; include=0; output;
  id=3; include=1; output;
  id=1; include=1; output;
run;
proc sort data=source out=selected;
  by descending id;
  where include=1;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        selected = sas.get_dataset("WORK", "SELECTED")
        self.assertEqual(selected["id"].tolist(), [3, 1])


class SasStatementCommentTests(unittest.TestCase):
    def test_unclosed_block_comment_discards_remaining_source(self) -> None:
        expander = MacroExpander()
        expanded = expander.expand(
            "data result; value=1; run; /* disabled remainder"
        )

        self.assertEqual(expanded.strip(), "data result; value=1; run;")

    def test_run_inside_block_comment_does_not_split_chunked_execution(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  value=1;
run;
proc sql noprint;
  select count(*) into :row_count from source;
quit;
/*
data disabled;
  value=999;
run;
*/
data result;
  value=&row_count;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertFalse(sas.session.dataset_exists("WORK", "DISABLED"))
        self.assertEqual(
            sas.get_dataset("WORK", "RESULT")["value"].tolist(),
            [1],
        )

    def test_leading_multiline_star_comment_is_removed_before_macro_expansion(self) -> None:
        expander = MacroExpander()
        expanded = expander.expand(
            """**** A commented-out macro statement
                  %let hidden=wrong ***;
%let visible=right;
data result;
  value="&visible";
run;
"""
        )

        self.assertIsNone(expander.get_var("hidden"))
        self.assertEqual(expander.get_var("visible"), "right")
        self.assertNotIn("wrong", expanded)
        self.assertIn('value="right"', expanded)

    def test_star_comments_work_between_statements_and_do_not_hide_sql_wildcard(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  id=1;
run; ****** comment between steps ******;
proc sql;
  create table copied as select * from source;
quit;
"""
        )

        self.assertTrue(result.success, result.error)
        copied = sas.get_dataset("WORK", "COPIED")
        self.assertEqual(copied["id"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
