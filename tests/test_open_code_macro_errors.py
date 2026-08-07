import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class OpenCodeMacroErrorTests(unittest.TestCase):
    def _execute(self, source: str):
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        return sas.execute(source), log.getvalue()

    def test_modern_open_code_if_is_allowed(self) -> None:
        result, log = self._execute("%if 1 %then %put yes;")

        self.assertTrue(result.success, result.error)
        self.assertEqual(log, "yes\n")

    def test_scope_only_statement_in_open_code_is_an_error(self) -> None:
        result, log = self._execute("%local orphan;")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Macro code is not allowed in open code.")
        self.assertEqual(log, "ERROR: Macro code is not allowed in open code.\n")

    def test_macro_control_statement_inside_macro_is_allowed(self) -> None:
        source = """
            %macro choose;
                %if 1 %then %put yes;
            %mend;
            %choose;
        """

        result, log = self._execute(source)

        self.assertTrue(result.success, result.error)
        self.assertEqual(log, "yes\n")

    def test_open_code_macro_text_inside_string_is_not_an_error(self) -> None:
        source = "data example; value = '%if is text'; run;"

        result, log = self._execute(source)

        self.assertTrue(result.success, result.error)
        self.assertNotIn("ERROR:", log)

    def test_open_code_let_remains_allowed(self) -> None:
        result, log = self._execute("%let value = 1;")

        self.assertTrue(result.success, result.error)
        self.assertNotIn("ERROR:", log)


if __name__ == "__main__":
    unittest.main()
