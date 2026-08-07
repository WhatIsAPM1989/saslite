import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class DataStepMergeWarningTests(unittest.TestCase):
    def _run(self, source: str):
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        result = sas.execute(source)
        return sas, result, log.getvalue()

    def test_many_to_many_by_group_emits_clear_warning(self) -> None:
        sas, result, log = self._run(
            """
data left_side;
  input id left_value;
  datalines;
1 10
1 20
;
run;
data right_side;
  input id right_value;
  datalines;
1 100
1 200
1 300
;
run;
data combined;
  merge left_side right_side;
  by id;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        warning = result.steps[-1].warnings[0]
        self.assertIn("Many-to-many MERGE detected", warning)
        self.assertIn("BY group ID=1", warning)
        self.assertIn("WORK.LEFT_SIDE (2 observations)", warning)
        self.assertIn("WORK.RIGHT_SIDE (3 observations)", warning)
        self.assertIn("not a Cartesian join", warning)
        self.assertIn(f"WARNING: {warning}", log)
        self.assertEqual(len(sas.get_dataset("WORK", "COMBINED")), 3)

    def test_one_repeating_input_does_not_emit_many_to_many_warning(self) -> None:
        _, result, log = self._run(
            """
data detail;
  input id value;
  datalines;
1 10
1 20
;
run;
data master;
  input id category $;
  datalines;
1 A
;
run;
data combined;
  merge detail master;
  by id;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.steps[-1].warnings, [])
        self.assertNotIn("Many-to-many MERGE", log)


if __name__ == "__main__":
    unittest.main()
