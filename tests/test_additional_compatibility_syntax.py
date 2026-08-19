import unittest

from saslite import SasInterpreter


class AdditionalCompatibilitySyntaxTests(unittest.TestCase):
    def test_hex_character_literal(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            'data result; rowlab="A0A0"x || "value"; run;'
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(frame["rowlab"].iloc[0], "\xa0\xa0value")

    def test_proc_freq_table_out_dataset(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data adverse_events;
  input category arm;
  datalines;
1 1
1 1
1 2
2 1
;
run;
proc freq data=adverse_events noprint;
  tables category*arm / out=freq2;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "FREQ2")
        self.assertEqual(frame["COUNT"].tolist(), [2, 1, 1])
        self.assertAlmostEqual(frame["PERCENT"].sum(), 100.0)

    def test_proc_freq_order_freq_sorts_output_by_descending_count(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data responses;
  input category;
  datalines;
1
2
2
2
3
3
;
run;
proc freq data=responses order=freq noprint;
  tables category / out=ordered;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "ORDERED")
        self.assertEqual(frame["CATEGORY"].tolist(), [2, 3, 1])
        self.assertEqual(frame["COUNT"].tolist(), [3, 2, 1])

    def test_proc_freq_out_accepts_drop_dataset_option(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data responses;
  input category;
  datalines;
1
1
2
;
run;
proc freq data=responses noprint;
  tables category / out=counts(drop=percent);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "COUNTS")
        self.assertEqual(list(frame.columns), ["CATEGORY", "COUNT"])

    def test_proc_freq_by_groups_counts_and_keeps_by_variable(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data responses;
  input treatment category;
  datalines;
1 10
1 10
1 20
2 10
2 20
2 20
2 20
;
run;
proc freq data=responses order=freq noprint;
  by treatment;
  tables category / out=counts(drop=percent);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "COUNTS")
        self.assertEqual(
            frame[["TREATMENT", "CATEGORY", "COUNT"]].values.tolist(),
            [[1, 10, 2], [1, 20, 1], [2, 20, 3], [2, 10, 1]],
        )

    def test_standalone_run_after_quit_is_a_noop(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
proc sql;
  create table first as select 1 as value;
quit;
run;
data second;
  value=2;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "SECOND")["value"].iloc[0], 2)

    def test_proc_means_output_accepts_dataset_options(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input group value;
  datalines;
1 10
1 20
;
run;
proc means data=source noprint;
  class group;
  var value;
  output out=stats(drop=_TYPE_ _FREQ_) mean=average;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "STATS")
        self.assertIn("AVERAGE", frame.columns)
        self.assertNotIn("_TYPE_", frame.columns)

    def test_character_format_accepts_unquoted_numeric_label(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
proc format;
  value $dcsreas "DEATH" = 2;
run;
data result;
  coded=put("DEATH", $dcsreas.);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["coded"].iloc[0], "2")

    def test_proc_data_option_accepts_where_dataset_option(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input group drug value;
  datalines;
1 0 10
1 1 20
2 1 30
;
run;
proc freq data=source(where=(drug=1)) noprint;
  tables group / out=counts;
run;
proc transpose data=source(where=(drug=1)) out=wide prefix=col;
  var value;
  id group;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        counts = sas.get_dataset("WORK", "COUNTS")
        self.assertEqual(counts["COUNT"].sum(), 2)
        wide = sas.get_dataset("WORK", "WIDE")
        self.assertEqual(len(wide), 1)

    def test_comparison_operator_may_contain_whitespace(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            "data result; value=9; lower=(8 < = value); upper=(value > = 8); run;"
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertTrue(frame["lower"].iloc[0])
        self.assertTrue(frame["upper"].iloc[0])

    def test_macro_definition_accepts_minoperator_option(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
%macro make_result(value=) / minoperator;
data result;
  value=&value;
run;
%mend;
%make_result(value=7)
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["value"].iloc[0], 7)

    def test_sql_column_attributes_accept_omitted_equals(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  value="value";
run;
proc sql;
  create table result as
  select value as text length 200 label "Display value"
  from source;
quit;
"""
        )

        self.assertTrue(result.success, result.error)
        dataset = sas.session.get_dataset("WORK", "RESULT")
        variable = dataset.metadata.get_variable("text")
        self.assertEqual(variable.length, 200)
        self.assertEqual(variable.label, "Display value")

    def test_quoted_macro_argument_remains_literal_before_sql_length(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  arm=1;
run;
%macro counts(order=, heading=);
  proc sql;
    create table result as
    select arm, &order as groupn,
           &heading as group_label length=200
    from source;
  quit;
%mend;
%counts(order=3, heading="Weight group (kg) at baseline");
"""
        )

        self.assertTrue(result.success, result.error)
        dataset = sas.session.get_dataset("WORK", "RESULT")
        self.assertEqual(
            dataset.data["group_label"].tolist(),
            ["Weight group (kg) at baseline"],
        )
        self.assertEqual(
            dataset.metadata.get_variable("group_label").length,
            200,
        )

    def test_put_and_input_accept_numeric_w_d_format_argument(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data result;
  length rendered $5;
  count=1;
  total=3;
  rendered=put((count/total)*100, 5.1);
  percentage=input(rendered, 5.1);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(frame["rendered"].iloc[0], " 33.3")
        self.assertAlmostEqual(frame["percentage"].iloc[0], 33.3)


if __name__ == "__main__":
    unittest.main()
