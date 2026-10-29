import io
import unittest
from unittest.mock import patch

import pandas as pd

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter
from saslite.executor.data_step.executor import DataStepExecutor
from saslite.runtime.dataset import Dataset


class UninitializedDeclarationTests(unittest.TestCase):
    @staticmethod
    def _warnings(result):
        return [w for w in result.steps[-1].warnings if "is uninitialized" in w]

    def test_visit_header_columns_warn_without_reading_them(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data visits; do avisitn=1 to 5; output; end; run; '
            'data visitrows; length termvar1 $200 col1-col3 $50; '
            'set visits; termvar1="Visit header"; statn=0; run;'
        )
        self.assertTrue(result.success, result.error)
        warnings = self._warnings(result)
        self.assertEqual(len(warnings), 3)
        for name in ("col1", "col2", "col3"):
            self.assertTrue(any(f"Variable {name} is uninitialized" in w for w in warnings))
        self.assertFalse(any("absent from input" in w or "fixture" in w for w in warnings))
        frame = sas.get_dataset("WORK", "VISITROWS")
        self.assertEqual(len(frame), 5)
        self.assertTrue((frame[["col1", "col2", "col3"]] == "").all().all())

    def test_zero_row_input_still_reports_output_only_declarations(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data empty; id=.; stop; run; '
            'data out; length text $20 number 8; set empty; run;'
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(len(self._warnings(result)), 2)
        self.assertEqual(len(sas.get_dataset("WORK", "OUT")), 0)

    def test_metadata_and_bare_retain_do_not_supply_values(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data out; length a $1; format b 8.; label c="Label"; '
            'attrib d length=8; retain e; run;'
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(len(self._warnings(result)), 5)

    def test_executable_sources_and_missing_input_values_do_not_warn(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data source; from_input=.; run; '
            'data out; set source; length conditional $1; '
            'if 0 then conditional="Y"; '
            'explicit=.; retain retained; retained=.; call missing(cleared); '
            'array values[2] first second (1, 2); '
            'do index=1 to 2; values[index]=.; end; run;'
        )
        self.assertTrue(result.success, result.error)
        self.assertFalse(self._warnings(result))

    def test_runtime_read_warning_is_not_duplicated(self):
        sas = SasInterpreter()
        result = sas.execute('data out; length col1 $1; value=col1; run;')
        self.assertTrue(result.success, result.error)
        self.assertEqual(len(self._warnings(result)), 1)

    def test_vectorized_step_keeps_declaration_diagnostics(self):
        sas = SasInterpreter()
        sas.session.put_dataset(
            "WORK", "SOURCE", Dataset.from_dataframe(pd.DataFrame({"X": [1, 2]}), "SOURCE")
        )
        with patch.object(
            DataStepExecutor, "_execute_statements",
            side_effect=AssertionError("row executor was used"),
        ):
            result = sas.execute('data out; set source; length unused 8; y=x*2; run;')
        self.assertTrue(result.success, result.error)
        self.assertEqual(len(self._warnings(result)), 1)
        self.assertIn("Variable unused is uninitialized", self._warnings(result)[0])

    def test_fail_fast_stops_after_uninitialized_declaration_step(self):
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log, quiet=True, stop_on_warning=True)
        result = sas.execute(
            'data first; length col1 $1; run; '
            'data should_not_run; value=1; run;'
        )
        self.assertFalse(result.success)
        self.assertTrue(sas.session.dataset_exists("WORK", "FIRST"))
        self.assertFalse(sas.session.dataset_exists("WORK", "SHOULD_NOT_RUN"))
        self.assertIn("Variable col1 is uninitialized", log.getvalue())


if __name__ == "__main__":
    unittest.main()
