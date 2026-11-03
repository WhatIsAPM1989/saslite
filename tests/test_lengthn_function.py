import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.functions import build_default_registry
from saslite.runtime.dataset import Dataset


class LengthnFunctionTests(unittest.TestCase):
    def test_registry_supports_lengthn_character_semantics(self):
        function = build_default_registry().get("LENGTHN")
        self.assertIsNotNone(function)
        cases = [("abc  ", 3), ("  ab  ", 4), ("a b ", 3), ("", 0), ("   ", 0), (None, 0)]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(function(text), expected)

    def test_data_step_lengthn_and_nested_strip(self):
        sas = SasInterpreter()
        result = sas.execute('''
            data wanted;
              length text $12;
              text="  abc  ";
              direct=lengthn(text);
              stripped=lengthn(strip(text));
              blank=lengthn("   ");
            run;
        ''')
        self.assertTrue(result.success, result.error)
        data = sas.get_dataset("WORK", "WANTED")
        self.assertEqual(data.direct.tolist(), [5])
        self.assertEqual(data.stripped.tolist(), [3])
        self.assertEqual(data.blank.tolist(), [0])

    def test_sql_lengthn_projection_and_blank_filter(self):
        sas = SasInterpreter()
        frame = pd.DataFrame({"text": ["abc  ", "  ab  ", "   "]})
        sas.session.put_dataset("WORK", "SOURCE", Dataset.from_dataframe(frame, "SOURCE"))
        result = sas.execute('''
            proc sql;
              create table wanted as
              select lengthn(text) as n from source
              where lengthn(text)>0;
            quit;
        ''')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "WANTED")["n"].tolist(), [3, 4])

    def test_length_and_lengthc_remain_unchanged(self):
        registry = build_default_registry()
        self.assertEqual(registry.get("LENGTH")("   "), 1)
        self.assertEqual(registry.get("LENGTHC")("abc  "), 5)


if __name__ == "__main__":
    unittest.main()
