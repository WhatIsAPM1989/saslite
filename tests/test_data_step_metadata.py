import unittest

from saslite import SasInterpreter


class DataStepMetadataTests(unittest.TestCase):
    def test_set_inherits_label_format_and_length(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length code $12;
  code="A01";
  label code="Subject code";
  format code $12.;
run;
data copied;
  set source;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        metadata = sas.session.get_dataset("WORK", "COPIED").metadata.get_variable("CODE")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.label, "Subject code")
        self.assertEqual(metadata.format, "$12.")
        self.assertEqual(metadata.length, 12)


if __name__ == "__main__":
    unittest.main()
