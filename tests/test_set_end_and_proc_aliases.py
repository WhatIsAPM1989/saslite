import unittest

from saslite import SasInterpreter


class SetEndAndProcAliasesTests(unittest.TestCase):
    def test_set_end_flag_is_available_but_not_written(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data source;
              input value;
              datalines;
            10
            20
            30
            ;
            run;
            data result;
              set source end=eof;
              if eof then final_value=value;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.reporter.warning_count, 0)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertNotIn("eof", frame.columns)
        self.assertEqual(frame["final_value"].iloc[-1], 30)

    def test_proc_format_accepts_lib_alias(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            proc format lib=work;
              value answer 1="Yes" 0="No";
            run;
            data rendered;
              value=1;
              label=put(value, answer.);
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RENDERED")["label"].iloc[0], "Yes")

    def test_proc_sort_preserves_input_libref_and_accepts_by_all(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data source;
              a=2; b=1; output;
              a=1; b=2; output;
            run;
            libname adam memory;
            data adam.source; set source; run;
            proc sort data=adam.source out=sorted;
              by _all_;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "SORTED")["a"].tolist(), [1, 2])

    def test_proc_import_accepts_replace_and_guessingrows(self) -> None:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "source.csv"
            csv_path.write_text("value\n1\n", encoding="utf-8")
            sas = SasInterpreter()
            result = sas.execute(
                f'''proc import out=loaded dbms=csv datafile="{csv_path}" replace;
                      getnames=yes;
                      guessingrows=max;
                    run;'''
            )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "LOADED")["value"].tolist(), [1])

    def test_coalesce_aggregate_over_empty_table_returns_one_row(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data empty;
              length grpx1 8;
              stop;
            run;
            proc sql noprint;
              select coalesce(max(grpx1), 1) into :maxgrp trimmed
              from empty;
            quit;
            data result;
              value=&maxgrp.;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["value"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
