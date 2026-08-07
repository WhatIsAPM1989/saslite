import io
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class SqlIntoTests(unittest.TestCase):
    def test_single_trimmed_count_distinct_target(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "adsl",
            pd.DataFrame({"trtn": [1, 1, 1, 2], "usubjid": ["01", "01", "02", "03"]}),
        )

        result = sas.execute(
            """
            proc sql noprint;
              select count(distinct usubjid) into :n1 trimmed
              from adsl where trtn=1;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.session.get_macro_var("n1"), "2")

    def test_multiple_targets_support_per_target_trimmed_modifier(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "analysis",
            pd.DataFrame({"first": ["  Alpha  "], "second": ["  Beta  "]}),
        )

        result = sas.execute(
            """
            proc sql noprint;
              select first, second
                into :n1 trimmed, :n2
              from analysis;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.session.get_macro_var("n1"), "Alpha")
        self.assertEqual(sas.session.get_macro_var("n2"), "  Beta  ")

    def test_multiple_unaliased_distinct_aggregates_assign_by_position(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "analysis",
            pd.DataFrame(
                {
                    "trtn": [1, 1, 1, 2, 3, 4],
                    "usubjid": ["01", "01", "02", "03", "04", "05"],
                }
            ),
        )

        result = sas.execute(
            """
            proc sql noprint;
              select count(distinct case when trtn=1 then usubjid else "" end),
                     count(distinct case when trtn=2 then usubjid else "" end),
                     count(distinct case when trtn=3 then usubjid else "" end),
                     count(distinct case when trtn=4 then usubjid else "" end)
                into :n1 trimmed, :n2 trimmed, :n3 trimmed, :n4 trimmed
              from analysis;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            [sas.session.get_macro_var(f"n{i}") for i in range(1, 5)],
            ["2", "1", "1", "1"],
        )

    def test_grouped_select_assigns_positional_into_targets(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "analysis",
            pd.DataFrame({"grp": [" B ", " A ", " A "]}),
        )

        result = sas.execute(
            """
            proc sql noprint;
              select grp, count(*) as n
                into :first_group trimmed, :first_count trimmed
              from analysis
              group by grp
              order by grp;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.session.get_macro_var("first_group"), "A")
        self.assertEqual(sas.session.get_macro_var("first_count"), "2")

    def test_separated_by_collects_all_ordered_rows_for_each_target(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "columns",
            pd.DataFrame(
                {
                    "ord": [3, 1, 2],
                    "name": [" third ", " first ", " second "],
                    "type": [" num ", " char ", " char "],
                }
            ),
        )

        result = sas.execute(
            """
            proc sql noprint;
              select name, type
                into :names separated by "|",
                     :types separated by " "
              from columns
              order by ord;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.session.get_macro_var("names"), "first|second|third")
        self.assertEqual(sas.session.get_macro_var("types"), "char char num")

    def test_separated_by_value_is_available_to_later_step(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "values",
            pd.DataFrame({"ord": [2, 1], "code": ["B", "A"]}),
        )

        result = sas.execute(
            """
            %let codes=;
            proc sql noprint;
              select code into :codes separated by ","
              from values order by ord;
            quit;

            data result;
              length text $20;
              text="&codes.";
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.session.get_macro_var("codes"), "A,B")
        self.assertEqual(
            sas.get_dataset("WORK", "RESULT").iloc[0]["text"],
            "A,B",
        )

    def test_into_value_is_available_to_later_step_and_macro_expansion(self) -> None:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        sas.create_dataset("analysis", pd.DataFrame({"usubjid": ["01", "02"]}))

        result = sas.execute(
            """
            proc sql noprint;
              select count(distinct usubjid) into :n1 trimmed
              from analysis;
            quit;

            %put resolved=&n1.;
            data result;
              value=&n1.;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertIn("resolved=2", log.getvalue())
        self.assertEqual(sas.get_dataset("WORK", "RESULT").iloc[0]["value"], 2)

    def test_into_value_is_available_later_in_expanded_macro_body(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("analysis", pd.DataFrame({"usubjid": ["01", "02"]}))

        result = sas.execute(
            """
            %macro build;
              proc sql noprint;
                select count(distinct usubjid) into :n1 trimmed
                from analysis;
              quit;
              data result;
                value=&n1.;
              run;
            %mend;
            %build;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").iloc[0]["value"], 2)

    def test_local_into_value_drives_iterative_macro_loop_at_runtime(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({"value": [10, 20, 30]}))

        result = sas.execute(
            """
            %macro build;
              %local row_count index;
              proc sql noprint;
                select count(*) into :row_count trimmed from source;
              quit;

              %do index=1 %to &row_count.;
                data result&index.;
                  value=&index.;
                run;
              %end;
            %mend;
            %build;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            [
                sas.get_dataset("WORK", f"RESULT{index}").iloc[0]["value"]
                for index in range(1, 4)
            ],
            [1, 2, 3],
        )

    def test_call_symput_value_drives_later_macro_conditional(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({"choice": [2]}))

        result = sas.execute(
            """
            %macro choose;
              %local selected;
              data _null_;
                set source;
                call symputx("selected", choice);
              run;

              %if &selected. = 2 %then %do;
                data result;
                  value=&selected.;
                run;
              %end;
              %else %do;
                data result;
                  value=0;
                run;
              %end;
            %mend;
            %choose;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").iloc[0]["value"], 2)

    def test_create_table_accepts_union_all_query(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "analysis",
            pd.DataFrame({"trtn": [1, 1, 2], "started": [1, 0, 1], "completed": [0, 1, 1]}),
        )

        result = sas.execute(
            """
            proc sql;
              create table event_counts as
              select trtn, 1 as row, count(*) as cnt
              from analysis where started=1 group by trtn
              union all
              select trtn, 2 as row, count(*) as cnt
              from analysis where completed=1 group by trtn;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "EVENT_COUNTS")
        self.assertEqual(actual.columns.tolist(), ["trtn", "row", "cnt"])
        self.assertEqual(len(actual), 4)

    def test_qualified_wildcard_expands_only_named_table_columns(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "adae",
            pd.DataFrame({"subjid": ["01", "02"], "aeterm": ["Headache", "Nausea"]}),
        )
        sas.create_dataset(
            "adsl",
            pd.DataFrame({"subjid": ["01", "02"], "trt01an": [1, 2], "trt01a": ["A", "B"]}),
        )

        result = sas.execute(
            """
            proc sql;
              create table joined as
              select a.*, b.trt01an, b.trt01a
              from adae as a inner join adsl as b
                on a.subjid=b.subjid;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "JOINED")
        self.assertEqual(actual.columns.tolist(), ["subjid", "aeterm", "trt01an", "trt01a"])
        self.assertEqual(actual["aeterm"].tolist(), ["Headache", "Nausea"])

    def test_grouped_coalesce_wrapped_aggregates_keep_aliases_and_fallbacks(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("shell", pd.DataFrame({"grp": [1, 2]}))
        sas.create_dataset(
            "detail",
            pd.DataFrame({"grp": [1, 1], "flag": [1, None], "value": [1, 2]}),
        )

        result = sas.execute(
            """
            proc sql;
              create table counts as
              select a.grp,
                     coalesce(sum(b.flag),0) as total,
                     coalesce(sum(b.value=1),0) as matches,
                     coalesce(count(b.flag),0) as present
              from shell as a left join detail as b
                on a.grp=b.grp
              group by a.grp
              order by a.grp;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "COUNTS")
        self.assertEqual(actual.columns.tolist(), ["grp", "total", "matches", "present"])
        self.assertEqual(
            actual.to_dict("records"),
            [
                {"grp": 1, "total": 1.0, "matches": 1, "present": 1},
                {"grp": 2, "total": 0.0, "matches": 0, "present": 0},
            ],
        )

    def test_comma_separated_from_sources_form_aliased_cross_join(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset("sg_shell", pd.DataFrame({"ord": [1, 2], "label": ["A", "B"]}))
        sas.create_dataset("trts", pd.DataFrame({"trtn": [10, 20]}))

        result = sas.execute(
            """
            proc sql;
              create table shell as
              select a.*, b.trtn
              from sg_shell as a, trts as b
              order by a.ord, b.trtn;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "SHELL")
        self.assertEqual(actual.columns.tolist(), ["ord", "label", "trtn"])
        self.assertEqual(
            actual.to_dict("records"),
            [
                {"ord": 1, "label": "A", "trtn": 10},
                {"ord": 1, "label": "A", "trtn": 20},
                {"ord": 2, "label": "B", "trtn": 10},
                {"ord": 2, "label": "B", "trtn": 20},
            ],
        )

    def test_grouped_left_join_uses_keys_from_temporary_array(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "base",
            pd.DataFrame(
                {
                    "subject": ["01", "02"],
                    "arm": [1, 1],
                    "all_value": ["All", "All"],
                    "status_value": ["Eligible", "Ineligible"],
                    "response": [1, 0],
                }
            ),
        )
        sas.create_dataset(
            "shell",
            pd.DataFrame(
                {
                    "key": ["all_key", "status_key"],
                    "value": ["All", "Eligible"],
                    "arm": [1, 1],
                }
            ),
        )

        result = sas.execute(
            """
            data long;
              length key $32 value $40;
              set base;
              array values[2] $40 all_value status_value;
              array keys[2] $32 _temporary_ ("all_key", "status_key");
              do index=1 to dim(values);
                key=keys[index];
                value=values[index];
                output;
              end;
              keep subject arm response key value;
            run;

            proc sql;
              create table counts as
              select a.key, a.value, a.arm,
                     count(distinct b.subject) as denominator,
                     coalesce(sum(b.response=1),0) as responders
              from shell as a left join long as b
                on a.key=b.key and a.value=b.value and a.arm=b.arm
              group by a.key, a.value, a.arm
              order by a.key;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        long_data = sas.get_dataset("WORK", "LONG")
        self.assertEqual(set(long_data["key"]), {"all_key", "status_key"})
        counts = sas.get_dataset("WORK", "COUNTS")
        self.assertEqual(
            counts.to_dict("records"),
            [
                {"key": "all_key", "value": "All", "arm": 1,
                 "denominator": 2, "responders": 1},
                {"key": "status_key", "value": "Eligible", "arm": 1,
                 "denominator": 1, "responders": 1},
            ],
        )


if __name__ == "__main__":
    unittest.main()
