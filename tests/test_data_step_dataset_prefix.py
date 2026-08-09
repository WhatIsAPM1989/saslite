import unittest

from saslite import SasInterpreter


class DataStepDatasetPrefixTests(unittest.TestCase):
    def test_set_expands_all_datasets_with_matching_prefix(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data row1; value=1; run;
            data unrelated; value=99; run;
            data row2; value=2; run;
            data combined; set row:; run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "COMBINED")["value"].tolist(),
            [1, 2],
        )

    def test_set_reports_an_unmatched_dataset_prefix(self) -> None:
        sas = SasInterpreter()
        result = sas.execute("data combined; set absent_:; run;")

        self.assertFalse(result.success)
        self.assertIn("No datasets match prefix", result.steps[-1].error or "")


if __name__ == "__main__":
    unittest.main()
