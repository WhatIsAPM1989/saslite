import math
import unittest

from saslite import SasInterpreter


class DataStepLagQueueTests(unittest.TestCase):
    def test_lag_and_dif_occurrences_have_independent_queues(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data result;
              input x;
              previous = lag(x);
              change = dif(x);
              second_previous = lag(x);
              datalines;
            2
            5
            9
            ;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        rows = sas.get_dataset("WORK", "RESULT").to_dict("records")
        self.assertTrue(math.isnan(rows[0]["previous"]))
        self.assertTrue(math.isnan(rows[0]["change"]))
        self.assertTrue(math.isnan(rows[0]["second_previous"]))
        self.assertEqual(
            rows[1:],
            [
                {"X": 5, "previous": 2, "change": 3, "second_previous": 2},
                {"X": 9, "previous": 5, "change": 4, "second_previous": 5},
            ],
        )


if __name__ == "__main__":
    unittest.main()
