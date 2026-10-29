import unittest

from saslite import SasInterpreter


class ArrayParenthesesTests(unittest.TestCase):
    def test_character_cells_are_read_and_written_in_report_loop(self) -> None:
        sas = SasInterpreter()
        result = sas.execute('''
            data source;
              length col1 col2 $50;
              col1=" 12 ( 3 ) "; col2=" 4 . 5 "; output;
              col1=" 6 ( 2 ) "; col2=" 7 . 8 "; output;
            run;
            data result;
              set source;
              array cells(*) $ col1-col2;
              do i=1 to dim(cells);
                cells(i)=compress(cells(i));
              end;
              keep col1 col2;
            run;
        ''')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").to_dict("records"), [
            {"col1": "12(3)", "col2": "4.5"},
            {"col1": "6(2)", "col2": "7.8"},
        ])

    def test_numeric_bounds_and_initial_values(self) -> None:
        sas = SasInterpreter()
        result = sas.execute('''
            data result;
              array values(2) first second (10,20);
              count=dim(values);
              values(2)=values(1)+5;
              selected=values(2);
              ordinary=sum(first,second);
            run;
        ''')
        self.assertTrue(result.success, result.error)
        row = sas.get_dataset("WORK", "RESULT").iloc[0]
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["first"], 10)
        self.assertEqual(row["second"], 15)
        self.assertEqual(row["selected"], 15)
        self.assertEqual(row["ordinary"], 25)

    def test_temporary_array_can_be_read_with_parentheses(self) -> None:
        sas = SasInterpreter()
        result = sas.execute('''
            data result;
              array lookup(2) _temporary_ (10,20);
              selected=lookup(2);
              count=dim(lookup);
            run;
        ''')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["selected"].tolist(), [20])
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["count"].tolist(), [2])

    def test_array_name_takes_precedence_over_builtin_function(self) -> None:
        sas = SasInterpreter()
        result = sas.execute('''
            data result;
              array sum(2) first second (10,20);
              selected=sum(2);
            run;
            data ordinary;
              selected=sum(10,20);
            run;
        ''')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT")["selected"].tolist(), [20])
        self.assertEqual(sas.get_dataset("WORK", "ORDINARY")["selected"].tolist(), [30])


if __name__ == "__main__":
    unittest.main()
