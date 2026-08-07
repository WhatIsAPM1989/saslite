import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class NestedMacroDefinitionTests(unittest.TestCase):
    def _interpreter(self) -> tuple[SasInterpreter, io.StringIO]:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        return sas, log

    def test_named_nested_definition_is_registered_when_outer_runs(self) -> None:
        sas, log = self._interpreter()
        source = """
            %macro outer(prefix=);
                %macro helper(value=);
                    %if &value = YES %then %put &prefix.-accepted;
                    %else %put &prefix.-rejected;
                %mend helper;
                %helper(value=YES);
            %mend outer;

            %outer(prefix=sample);
            %put after-outer;
        """

        result = sas.execute(source)

        self.assertTrue(result.success, result.error)
        # Existing macro expansion processes open-code %PUT statements before
        # those emitted by an invoked macro.
        self.assertEqual(log.getvalue(), "after-outer\nsample-accepted\n")
        self.assertIn("OUTER", sas._macro._macros)
        self.assertIn("HELPER", sas._macro._macros)

    def test_depth_aware_extraction_supports_multiple_nested_levels(self) -> None:
        sas, log = self._interpreter()
        source = """
            %macro outer;
                %macro middle;
                    %macro inner;
                        %put deepest;
                    %mend inner;
                    %inner;
                %mend middle;
                %middle;
            %mend outer;
            %outer;
        """

        result = sas.execute(source)

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "deepest\n")

    def test_nested_macro_invocation_respects_outer_conditional(self) -> None:
        sas, log = self._interpreter()
        definition = """
            %macro outer(enabled=);
                %macro helper;
                    %put helper-ran;
                %mend helper;
                %if &enabled = 1 %then %do;
                    %helper;
                %end;
            %mend outer;
        """

        defined = sas.execute(definition)
        disabled = sas.execute("%outer(enabled=0);")
        enabled = sas.execute("%outer(enabled=1);")

        self.assertTrue(defined.success, defined.error)
        self.assertTrue(disabled.success, disabled.error)
        self.assertTrue(enabled.success, enabled.error)
        self.assertEqual(log.getvalue(), "helper-ran\n")

    def test_named_mend_must_match_macro_name(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            "%macro outer; %put no; %mend different;"
        )

        self.assertFalse(result.success)
        self.assertEqual(
            result.error,
            "%MEND different does not match %MACRO OUTER",
        )
        self.assertEqual(
            log.getvalue(),
            "ERROR: %MEND different does not match %MACRO OUTER\n",
        )

    def test_local_variables_are_scoped_and_parameters_keep_values(self) -> None:
        sas, log = self._interpreter()
        defined = sas.execute(
            """
            %let shared=outer;
            %macro inspect(value=default);
                %local value scratch shared;
                %let scratch=inside;
                %let shared=local;
                %put VALUE=&value SCRATCH=&scratch SHARED=&shared;
            %mend inspect;
            """
        )
        invoked = sas.execute("%inspect(value=kept);")

        self.assertTrue(defined.success, defined.error)
        self.assertTrue(invoked.success, invoked.error)
        self.assertEqual(
            log.getvalue(),
            "VALUE=kept SCRATCH=inside SHARED=local\n",
        )
        self.assertEqual(sas._macro.get_var("shared"), "outer")
        self.assertIsNone(sas._macro.get_var("scratch"))

    def test_local_statement_is_removed_from_emitted_sas(self) -> None:
        sas, _log = self._interpreter()
        result = sas.execute(
            """
            %macro build;
                %local value;
                %let value=7;
                data result;
                    number=&value;
                run;
            %mend build;
            %build;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "RESULT").iloc[0]["number"],
            7,
        )
        self.assertIsNone(sas._macro.get_var("value"))

    def test_nested_if_do_else_blocks_choose_only_matching_branch(self) -> None:
        sas, log = self._interpreter()
        defined = sas.execute(
            """
            %macro choose(outer=, inner=);
                %if &outer = 1 %then %do;
                    %if &inner = 1 %then %do;
                        %put both;
                    %end;
                    %else %do;
                        %put outer-only;
                    %end;
                %end;
                %else %do;
                    %put neither;
                %end;
            %mend choose;
            """
        )

        first = sas.execute("%choose(outer=1, inner=1);")
        second = sas.execute("%choose(outer=1, inner=0);")
        third = sas.execute("%choose(outer=0, inner=1);")

        self.assertTrue(defined.success, defined.error)
        self.assertTrue(first.success, first.error)
        self.assertTrue(second.success, second.error)
        self.assertTrue(third.success, third.error)
        self.assertEqual(log.getvalue(), "both\nouter-only\nneither\n")

    def test_false_nested_branch_leaves_no_macro_end_in_emitted_sas(self) -> None:
        sas, _log = self._interpreter()
        result = sas.execute(
            """
            %macro build(enabled=);
                %if &enabled = 1 %then %do;
                    %if 1 %then %do;
                        data unwanted; value=0; run;
                    %end;
                %end;
                %else %do;
                    data wanted; value=1; run;
                %end;
            %mend build;
            %build(enabled=0);
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertFalse(sas.session.dataset_exists("WORK", "UNWANTED"))
        self.assertEqual(sas.get_dataset("WORK", "WANTED").iloc[0]["value"], 1)

    def test_superq_preserves_spaces_and_does_not_resolve_ampersand(self) -> None:
        sas, log = self._interpreter()
        sas._macro.set_var("LATER", "resolved")
        sas._macro.set_var("RAW", "  alpha &LATER beta  ")

        result = sas.execute("%put VALUE=[%superq(RAW)];")

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "VALUE=[  alpha &LATER beta  ]\n")

    def test_superq_reads_current_invocation_scope(self) -> None:
        sas, log = self._interpreter()
        result = sas.execute(
            """
            %macro show(value=);
                %put LOCAL=[%superq(value)];
            %mend show;
            %show(value=left &unresolved right);
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(log.getvalue(), "LOCAL=[left &unresolved right]\n")


if __name__ == "__main__":
    unittest.main()
