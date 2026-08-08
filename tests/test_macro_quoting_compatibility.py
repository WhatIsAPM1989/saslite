import unittest

from saslite import SasInterpreter


class MacroQuotingCompatibilityTests(unittest.TestCase):
    def test_nested_unresolved_function_does_not_truncate_macro_call(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
%macro no_op(intitle=,suffix=,style=);
%mend no_op;
%no_op(
  intitle=titles,
  suffix=a,
  outdir=root/%scan(&unresolved_path.,3,/)/output,
  outtype=rtf,
  style=AZRTF
);
data result;
  value=1;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "RESULT")["value"].tolist(),
            [1],
        )

    def test_str_masks_expression_passed_as_keyword_argument(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length region $20;
  region="North America"; output;
  region="Europe"; output;
run;
%macro select_rows(subset=);
  data selected;
    set source(where=(&subset.));
  run;
%mend;
%select_rows(subset=%str(region='North America'));
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "SELECTED")["region"].tolist(),
            ["North America"],
        )

    def test_unquoted_keyword_expression_keeps_its_trailing_quote(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length region $20;
  region="Asia"; output;
  region="Europe"; output;
run;
%macro select_rows(subset=);
  data selected;
    set source(where=(&subset.));
  run;
%mend;
%select_rows(subset=region='Asia');
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "SELECTED")["region"].tolist(),
            ["Asia"],
        )

    def test_else_if_with_empty_length_removes_macro_control_tokens(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
%let numeric_name=;
%let character_name=valuec;
%macro build;
data result;
  valuec="12";
  selected=.;
  %if %length(&numeric_name.) %then %do;
    selected=&numeric_name.;
  %end;
  %else %if %length(&character_name.) %then %do;
    selected=input(&character_name., best.);
  %end;
run;
%mend;
%build;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "RESULT")["selected"].tolist(),
            [12.0],
        )


if __name__ == "__main__":
    unittest.main()
