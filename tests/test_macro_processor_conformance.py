import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class MacroProcessorConformanceTests(unittest.TestCase):
    def _interpreter(self) -> tuple[SasInterpreter, io.StringIO]:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        return sas, log

    def test_let_preserves_quotes_as_macro_text(self) -> None:
        sas, _log = self._interpreter()

        result = sas.execute(
            '''
%let literal="Alpha";
data result;
  length value $10;
  value=&literal;
run;
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["value"].tolist(), ["Alpha"])

    def test_let_balances_macro_quoting_before_finding_semicolon(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%let statement=%str(alpha,beta; gamma); "
            "%put VALUE=[&statement];"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "VALUE=[alpha,beta; gamma]\n")

    def test_eval_balanced_parentheses_and_left_associativity(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%put NESTED=%eval((1+2)*(3+1)) LEFT=%eval(10-3-2) DIV=%eval(7/2);"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "NESTED=12 LEFT=5 DIV=3\n")

    def test_sysevalf_conversion_types(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%put FLOAT=%sysevalf(7/2) TRUE=%sysevalf(.5,boolean) "
            "FALSE=%sysevalf(0,boolean) CEIL=%sysevalf(1.2,ceil) "
            "FLOOR=%sysevalf(1.8,floor);"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            log.getvalue(),
            "FLOAT=3.5 TRUE=1 FALSE=0 CEIL=2 FLOOR=1\n",
        )

    def test_multiple_ampersands_rescan_until_stable(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%let stem=city; %let n=6; %let city6=Boston; "
            "%put VALUE=&&&stem&n;"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "VALUE=Boston\n")

    def test_macro_calls_and_assignments_execute_in_source_order(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%macro show;
  %put VALUE=&value;
%mend;
%let value=before;
%show;
%let value=after;
%show;
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "VALUE=before\nVALUE=after\n")

    def test_user_macro_can_generate_a_let_value(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%macro echo(value);
&value
%mend;
%let captured=%echo(Alpha);
%put CAPTURED=&captured;
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "CAPTURED=Alpha\n")

    def test_recursive_macro_invocation_has_isolated_local_scopes(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%macro countdown(n);
  %if &n > 0 %then %do;
    %put N=&n;
    %countdown(%eval(&n-1));
  %end;
%mend;
%countdown(3);
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "N=3\nN=2\nN=1\n")

    def test_runtime_quoting_masks_commas_in_macro_arguments(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%macro show(value=);
  %put VALUE=[&value];
%mend;
%let text=Alpha, Beta;
%show(value=%bquote(&text));
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "VALUE=[Alpha, Beta]\n")

    def test_nrquote_masks_macro_triggers_and_unquote_reenables_them(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%let later=resolved;
%let raw=&later;
%put MASKED=[%nrquote(&raw)];
%put UNMASKED=[%unquote(%nrstr(&later))];
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            log.getvalue(),
            "MASKED=[resolved]\nUNMASKED=[resolved]\n",
        )

    def test_qscan_and_qsubstr_return_quoted_results(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%let text=alpha|beta&unresolved; "
            "%put WORD=[%qscan(%superq(text),2,|)] "
            "PART=[%qsubstr(%superq(text),7,15)];"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            log.getvalue(),
            "WORD=[beta&unresolved] PART=[beta&unresolved]\n",
        )

    def test_sysfunc_applies_optional_output_format(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%put VALUE=[%sysfunc(sum(1,2.5),8.2)];"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "VALUE=[    3.50]\n")

    def test_symexist_symlocal_symglobl_and_symdel(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%global shared;
%let shared=outside;
%macro inspect;
  %local local_only;
  %let local_only=inside;
  %put LOCAL=%symlocal(local_only) GLOBAL=%symglobl(shared)
       BOTH=%symexist(shared);
%mend;
%inspect;
%symdel shared / nowarn;
%put AFTER=%symexist(shared);
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            " ".join(log.getvalue().split()),
            "LOCAL=1 GLOBAL=1 BOTH=1 AFTER=0",
        )

    def test_do_while_rechecks_condition_after_each_iteration(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%macro count;
  %local i;
  %let i=0;
  %do %while(&i < 3);
    %let i=%eval(&i+1);
    %put I=&i;
  %end;
%mend;
%count;
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "I=1\nI=2\nI=3\n")

    def test_do_until_executes_body_before_checking_condition(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            '''
%macro count;
  %local i;
  %let i=0;
  %do %until(&i >= 2);
    %let i=%eval(&i+1);
    %put I=&i;
  %end;
%mend;
%count;
'''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "I=1\nI=2\n")


if __name__ == "__main__":
    unittest.main()
