import unittest

from saslite import SasInterpreter


class QuotedDatalinesInputTests(unittest.TestCase):
    def test_dsd_honors_quoted_delimiters_and_empty_fields(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            r'''
            data parsed;
              infile datalines dsd dlm=',' truncover;
              length name $ 20 note $ 40;
              input name :$20. note :$40.;
              datalines;
            "Smith, John","hello, world"
            "Jones, Ann",
            ;
            run;
            '''
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "PARSED")
        self.assertEqual(
            frame.to_dict("records"),
            [
                {"NAME": "Smith, John", "NOTE": "hello, world"},
                {"NAME": "Jones, Ann", "NOTE": ""},
            ],
        )

    def test_quoted_list_input_survives_datalines_preprocessing(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            r'''
            data parsed;
              length name $ 20 value 8;
              input name $ value;
              datalines;
            "Jane Doe" 7
            ;
            run;
            '''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "PARSED").to_dict("records"),
            [{"NAME": "Jane Doe", "VALUE": 7}],
        )

    def test_datalines4_allows_semicolons_in_raw_records(self) -> None:
        sas = SasInterpreter()

        result = sas.execute(
            r'''
            data parsed;
              infile datalines4 dsd dlm='|';
              input text :$20. value;
              datalines4;
            "A;B"|1
            "C"|2
            ;;;;
            run;
            '''
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "PARSED").to_dict("records"),
            [
                {"TEXT": "A;B", "VALUE": 1},
                {"TEXT": "C", "VALUE": 2},
            ],
        )


if __name__ == "__main__":
    unittest.main()
