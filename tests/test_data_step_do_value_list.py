import unittest

from saslite import SasInterpreter


class DataStepDoValueListTests(unittest.TestCase):
    def test_explicit_value_list(self):
        sas = SasInterpreter()
        execution = sas.execute(
            """
            data out;
              do trt = 1, 2, 3, 99;
                value = trt * 10;
                output;
              end;
            run;
            """
        )

        self.assertTrue(execution.success, execution.error)
        result = sas.get_dataset("WORK", "OUT")
        self.assertEqual(result["trt"].tolist(), [1, 2, 3, 99])
        self.assertEqual(result["value"].tolist(), [10, 20, 30, 990])


if __name__ == "__main__":
    unittest.main()
