import io
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class SetLengthWarningTests(unittest.TestCase):
    def _interpreter_with_sources(self, first_length: int, second_length: int):
        sas = SasInterpreter()
        sas.create_dataset("first", pd.DataFrame({"value": ["a"]}))
        sas.create_dataset("second", pd.DataFrame({"value": ["bb"]}))
        sas.session.get_dataset("WORK", "FIRST").metadata.variables["VALUE"].length = first_length
        sas.session.get_dataset("WORK", "SECOND").metadata.variables["VALUE"].length = second_length

        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        return sas, log

    def test_set_warns_when_common_variable_lengths_differ(self) -> None:
        sas, log = self._interpreter_with_sources(8, 16)

        result = sas.execute("data combined; set first second; run;")

        self.assertTrue(result.success, result.error)
        expected = (
            "Multiple lengths were specified for the variable value by input data set(s). "
            "Different lengths: 8, 16. "
            "This can cause truncation of data."
        )
        self.assertEqual(result.steps[-1].warnings, [expected])
        self.assertIn(f"WARNING: {expected}", log.getvalue())

    def test_set_does_not_warn_when_common_variable_lengths_match(self) -> None:
        sas, log = self._interpreter_with_sources(8, 8)

        result = sas.execute("data combined; set first second; run;")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.steps[-1].warnings, [])
        self.assertNotIn("WARNING:", log.getvalue())


if __name__ == "__main__":
    unittest.main()
