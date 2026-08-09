import unittest

from saslite import SasInterpreter


class DataStepUpdateTests(unittest.TestCase):
    def test_update_overlays_nonmissing_transaction_values_by_key(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data master;
              input id name $ amount;
              datalines;
            1 A 10
            2 B 20
            3 C 30
            ;
            run;

            data changes;
              input id name $ amount;
              datalines;
            0 Z 5
            2 B2 25
            3 . 35
            4 D 40
            ;
            run;

            data result;
              update master changes;
              by id;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "RESULT").to_dict("records"),
            [
                {"ID": 0, "NAME": "Z", "AMOUNT": 5},
                {"ID": 1, "NAME": "A", "AMOUNT": 10},
                {"ID": 2, "NAME": "B2", "AMOUNT": 25},
                {"ID": 3, "NAME": "C", "AMOUNT": 35},
                {"ID": 4, "NAME": "D", "AMOUNT": 40},
            ],
        )

    def test_update_requires_by_statement(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data master; id=1; run;
            data changes; id=1; run;
            data result; update master changes; run;
            """
        )

        self.assertFalse(result.success)
        self.assertIn(
            "UPDATE requires a BY statement",
            result.steps[-1].error or "",
        )


if __name__ == "__main__":
    unittest.main()
