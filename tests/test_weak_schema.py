import io
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.storage.memory import MemoryBackend


class WeakSchemaTests(unittest.TestCase):
    def test_expectation_keeps_the_more_precise_source_lineage(self) -> None:
        sas = SasInterpreter()
        sas.session.record_schema_expectation(
            "aeterm",
            ["ADAM.ADAE", "ADAM.ADSL"],
            "DATA step",
        )
        sas.session.record_schema_expectation(
            "aeterm",
            ["ADAM.ADAE"],
            "SELECT",
        )

        self.assertEqual(len(sas.session.schema_expectations), 1)
        expectation = sas.session.schema_expectations[0]
        self.assertEqual(expectation.sources, ("ADAM.ADAE",))
        self.assertEqual(expectation.contexts, ("DATA STEP", "SELECT"))

    def test_missing_input_variable_is_assumed_without_mutating_source(self) -> None:
        sas = SasInterpreter()
        sas.session.storage.register("ADAM", MemoryBackend())
        sas.create_dataset("adae", pd.DataFrame({"USUBJID": ["TEST-001"]}), libref="ADAM")
        log = io.StringIO()
        sas.reporter._stream = log
        sas.reporter.configure(quiet=True)

        result = sas.execute(
            "data result; set adam.adae; selected=(trtemfl='Y'); run;"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(list(sas.get_dataset("ADAM", "ADAE").columns), ["USUBJID"])
        self.assertFalse(result.steps[-1].warnings)
        self.assertEqual(len(sas.session.schema_expectations), 1)
        expectation = sas.session.schema_expectations[0]
        self.assertEqual(expectation.sources, ("ADAM.ADAE",))
        self.assertEqual(expectation.variable, "TRTEMFL")
        self.assertEqual(expectation.contexts, ("DATA STEP",))
        self.assertIn("ADAM.ADAE.TRTEMFL", log.getvalue())
        self.assertIn("Validation level: weak", log.getvalue())

    def test_work_is_strict_even_for_imported_datasets(self) -> None:
        sas = SasInterpreter()
        self.assertEqual(sas.session.schema_policy_for("work"), "strict")
        self.assertEqual(sas.session.schema_policy_for("RAW"), "weak")
        sas.create_dataset("source", pd.DataFrame({"known": [1]}))
        result = sas.execute("data result; set source; value=unknown; run;")
        self.assertTrue(result.success, result.error)
        self.assertFalse(sas.session.schema_expectations)
        self.assertIn("UNKNOWN", "\n".join(result.steps[-1].warnings).upper())

    def test_work_intermediates_report_the_original_source_schema(self) -> None:
        sas = SasInterpreter()
        sas.session.storage.register("ADAM", MemoryBackend())
        sas.create_dataset(
            "adae",
            pd.DataFrame({"USUBJID": ["TEST-001"]}),
            libref="ADAM",
        )

        result = sas.execute(
            """
proc sort data=adam.adae out=adae;
  by usubjid;
run;
data adae2;
  set adae;
run;
data result;
  set adae2;
  selected=(trtemfl='Y');
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(sas.session.schema_expectations), 1)
        expectation = sas.session.schema_expectations[0]
        self.assertEqual(expectation.sources, ("ADAM.ADAE",))
        self.assertEqual(expectation.variable, "TRTEMFL")

    def test_closed_work_dataset_does_not_become_a_weak_source(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data generated;
  value=1;
run;
data result;
  set generated;
  selected=(not_created='Y');
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertFalse(sas.session.schema_expectations)
        warnings = "\n".join(result.steps[-1].warnings).upper()
        self.assertIn("NOT_CREATED", warnings)
        self.assertIn("WORK.GENERATED", warnings)


if __name__ == "__main__":
    unittest.main()
