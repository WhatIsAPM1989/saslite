import unittest

from saslite import SasInterpreter
from saslite.functions.numeric_funcs import cmiss


class CmissFunctionTests(unittest.TestCase):
    def test_counts_mixed_numeric_and_character_missing_values(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data counts;
  blank="";
  blanks="   ";
  period=".";
  number_missing=input("", best.);
  present_number=0;
  present_text="value";
  missing_count=cmiss(
    blank, blanks, period, number_missing, present_number, present_text
  );
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "COUNTS")
        self.assertEqual(frame.loc[0, "missing_count"], 3)

    def test_accepts_null_like_values_and_no_arguments(self) -> None:
        self.assertEqual(cmiss(), 0)
        self.assertEqual(cmiss(None, float("nan"), "", "  ", ".", 0), 4)


if __name__ == "__main__":
    unittest.main()
