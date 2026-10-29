import unittest

from saslite import SasInterpreter


class LengthTrailingPeriodTests(unittest.TestCase):
    def test_grouped_character_and_numeric_widths_preserve_names_and_types(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data out; length first second $10. numeric 8.; '
            'first="a"; second="b"; numeric=1; run;'
        )
        self.assertTrue(result.success, result.error)
        self.assertFalse(result.steps[-1].warnings)
        dataset = sas.session.get_dataset("WORK", "OUT")
        self.assertEqual(list(dataset.data.columns), ["first", "second", "numeric"])
        for name in ("first", "second"):
            meta = dataset.metadata.get_variable(name)
            self.assertEqual((meta.dtype, meta.length), ("character", 10))
        meta = dataset.metadata.get_variable("numeric")
        self.assertEqual((meta.dtype, meta.length), ("numeric", 8))

    def test_numbered_ranges_allow_trailing_period(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data out; length col1-col3 $20. value1-value2 8.; '
            'col1="a"; col2="b"; col3="c"; value1=1; value2=2; run;'
        )
        self.assertTrue(result.success, result.error)
        self.assertFalse(result.steps[-1].warnings)
        dataset = sas.session.get_dataset("WORK", "OUT")
        self.assertEqual(set(dataset.metadata.variables), {"COL1", "COL2", "COL3", "VALUE1", "VALUE2"})
        for name in ("COL1", "COL2", "COL3"):
            meta = dataset.metadata.get_variable(name)
            self.assertEqual((meta.dtype, meta.length), ("character", 20))

    def test_uninitialized_note_names_actual_declared_variable(self):
        sas = SasInterpreter()
        result = sas.execute('data out; length unused $10.; run;')
        self.assertTrue(result.success, result.error)
        warnings = result.steps[-1].warnings
        self.assertEqual(len(warnings), 1)
        self.assertIn("Variable unused is uninitialized", warnings[0])
        self.assertEqual(list(sas.get_dataset("WORK", "OUT").columns), ["unused"])

    def test_empty_input_keeps_declarations_with_trailing_period(self):
        sas = SasInterpreter()
        result = sas.execute(
            'data source; id=.; stop; run; '
            'data out; length text $12. numeric 8.; set source; '
            'text=""; numeric=.; run;'
        )
        self.assertTrue(result.success, result.error)
        self.assertFalse(result.steps[-1].warnings)
        dataset = sas.session.get_dataset("WORK", "OUT")
        self.assertEqual(len(dataset.data), 0)
        self.assertEqual(set(dataset.metadata.variables), {"ID", "TEXT", "NUMERIC"})
        self.assertEqual(dataset.metadata.get_variable("TEXT").length, 12)


if __name__ == "__main__":
    unittest.main()
