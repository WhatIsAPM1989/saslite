import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class CharacterLengthWarningTests(unittest.TestCase):
    def _interpreter(self):
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        return sas, log

    def test_overlong_assignment_is_preserved_and_warned(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            'data result; length code $3; code="ABCDE"; run;'
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["code"].tolist(), ["ABCDE"])
        self.assertEqual(len(result.steps[-1].warnings), 1)
        warning = result.steps[-1].warnings[0]
        self.assertIn("Character truncation risk for variable code", warning)
        self.assertIn("declared LENGTH 3 bytes", warning)
        self.assertIn("maximum 5 bytes", warning)
        self.assertIn("first at _N_=1: 'ABCDE'", warning)
        self.assertIn("SASLite preserved it for validation", warning)
        self.assertIn("Increase LENGTH", warning)
        self.assertIn(f"WARNING: {warning}", log.getvalue())

    def test_repeated_overflows_are_aggregated_per_variable(self) -> None:
        sas, _ = self._interpreter()

        result = sas.execute(
            """
data source;
  input code $;
  datalines;
ABCDE
LONGER
;
run;
data result;
  length code $3;
  set source;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        warnings = result.steps[-1].warnings
        self.assertEqual(len(warnings), 1)
        self.assertIn("2 values exceeded", warnings[0])
        self.assertIn("maximum 6 bytes", warnings[0])
        frame = sas.get_dataset("WORK", "RESULT")
        code_column = next(column for column in frame if column.upper() == "CODE")
        self.assertEqual(frame[code_column].tolist(), ["ABCDE", "LONGER"])

    def test_value_at_declared_length_does_not_warn(self) -> None:
        sas, log = self._interpreter()

        result = sas.execute(
            'data result; length code $5; code="ABCDE"; run;'
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.steps[-1].warnings, [])
        self.assertNotIn("Character truncation risk", log.getvalue())

    def test_runtime_encoding_is_used_for_byte_length(self) -> None:
        sas, _ = self._interpreter()

        result = sas.execute(
            'options encoding="utf-8"; data result; length code $2; code="éé"; run;'
        )

        self.assertTrue(result.success, result.error)
        warning = result.steps[-1].warnings[0]
        self.assertIn("declared LENGTH 2 bytes", warning)
        self.assertIn("maximum 4 bytes", warning)
        self.assertIn("encoding utf-8", warning)


if __name__ == "__main__":
    unittest.main()
