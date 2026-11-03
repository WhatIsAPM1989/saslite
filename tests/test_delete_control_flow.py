import unittest

from saslite import SasInterpreter


class DeleteControlFlowTests(unittest.TestCase):
    def _execute(self, body):
        sas = SasInterpreter()
        result = sas.execute(f'''
            data source; x=1; output; x=2; output; run;
            data wanted; set source; {body} run;
        ''')
        self.assertTrue(result.success, result.error)
        return sas.get_dataset("WORK", "WANTED")

    def test_conditional_delete_skips_later_validation(self):
        data = self._execute('''
            if x=1 then delete;
            if x=1 then do;
                putlog "ERROR: deleted observation continued";
                abort cancel;
            end;
        ''')
        self.assertEqual(data.x.tolist(), [2])

    def test_unconditional_delete_ends_the_iteration(self):
        data = self._execute("delete; abort cancel;")
        self.assertTrue(data.empty)

    def test_false_subsetting_if_skips_later_statements(self):
        data = self._execute("if x=2; if x=1 then abort cancel;")
        self.assertEqual(data.x.tolist(), [2])

    def test_else_delete_resumes_with_next_observation(self):
        data = self._execute('''
            if x=2 then marker=1; else delete;
            if x=1 then abort cancel;
        ''')
        self.assertEqual(data.x.tolist(), [2])
        self.assertEqual(data.marker.tolist(), [1])

    def test_nested_do_delete_propagates_to_outer_statement_lists(self):
        data = self._execute('''
            if x=1 then do;
                do;
                    delete;
                    abort cancel;
                end;
                abort cancel;
            end;
            if x=1 then abort cancel;
        ''')
        self.assertEqual(data.x.tolist(), [2])

    def test_output_before_delete_survives_but_output_afterward_does_not(self):
        data = self._execute("output; delete; x=99; output;")
        self.assertEqual(data.x.tolist(), [1, 2])


if __name__ == "__main__":
    unittest.main()
