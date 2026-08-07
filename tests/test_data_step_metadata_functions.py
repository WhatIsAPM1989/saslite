import unittest

from saslite import SasInterpreter


class DataStepMetadataFunctionTests(unittest.TestCase):
    def test_vlabel_returns_label_or_variable_name(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length response $1 unlabelled $3;
  response="Y";
  unlabelled="raw";
  label response="Participant response";
run;

data labels;
  set source;
  response_label=vlabel(response);
  fallback_label=vlabel(unlabelled);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "LABELS")
        self.assertEqual(frame["response_label"].tolist(), ["Participant response"])
        self.assertEqual(frame["fallback_label"].tolist(), ["unlabelled"])


if __name__ == "__main__":
    unittest.main()
