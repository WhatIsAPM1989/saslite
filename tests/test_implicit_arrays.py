import unittest
from saslite import SasInterpreter


class ImplicitArrayTests(unittest.TestCase):
    def test_character_selector_and_do_over_update_all_rows(self):
        sas = SasInterpreter()
        result = sas.execute("""
          data source;
            length col1 col2 $30;
            col1=' 2 ( 1 ) '; col2=' 3 . 4 '; number=5; output;
            col1=' 6 ( 2 ) '; col2=' 7 . 8 '; number=9; output;
          run;
          data result;
            set source;
            array chars _character_;
            do over chars; chars=compress(chars); end;
            drop _i_;
          run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset('WORK', 'RESULT').to_dict('records'), [
            {'col1': '2(1)', 'col2': '3.4', 'number': 5},
            {'col1': '6(2)', 'col2': '7.8', 'number': 9},
        ])
        self.assertFalse([w for step in result.steps for w in step.warnings])

    def test_explicit_index_character_selector_preserves_numeric_variable(self):
        sas = SasInterpreter()
        result = sas.execute("""
          data result;
            length a b $20;
            array chars(*) _character_;
            a=' 1 2 '; b=' 3 4 '; n=7;
            do j=1 to dim(chars); chars(j)=compress(chars(j)); end;
            keep a b n;
          run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset('WORK', 'RESULT').to_dict('records'),
                         [{'a': '12', 'b': '34', 'n': 7}])

    def test_numeric_do_over_with_nested_if(self):
        sas = SasInterpreter()
        result = sas.execute("""
          data result;
            array nums a b (1,2);
            do over nums;
              if nums>1 then nums=nums+10;
            end;
            keep a b;
          run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset('WORK', 'RESULT').to_dict('records'),
                         [{'a': 1, 'b': 12}])

    def test_zero_row_input_preserves_descriptor_without_array_pseudo_variables(self):
        sas = SasInterpreter()
        result = sas.execute("""
          data source; length a $20; a=''; stop; run;
          data result; set source; array chars _character_;
            do over chars; chars=compress(chars); end; drop _i_;
          run;
        """)
        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset('WORK', 'RESULT')
        self.assertEqual(len(frame), 0)
        self.assertEqual(list(frame.columns), ['a'])


if __name__ == '__main__':
    unittest.main()
