import unittest
from saslite import SasInterpreter


class NestedDeclarationTests(unittest.TestCase):
    def test_nested_length_precedes_later_label(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                sas = SasInterpreter()
                source = "data source; id=1; " + ("stop;" if empty else "") + " run;"
                result = sas.execute(source + """
                    data result;
                      set source;
                      if id=1 then do;
                        length text $200;
                        text='0';
                      end;
                      label text='Count';
                    run;
                """)
                self.assertTrue(result.success, result.error)
                self.assertFalse([w for step in result.steps for w in step.warnings])
                ds = sas.session.get_dataset('WORK', 'RESULT')
                meta = ds.metadata.get_variable('TEXT')
                self.assertEqual((meta.dtype, meta.length, meta.label), ('character', 200, 'Count'))
                if not empty:
                    self.assertEqual(ds.data['text'].tolist(), ['0'])

    def test_empty_data_numeric_keys_survive_sql_and_merge(self):
        sas = SasInterpreter()
        result = sas.execute("""
            data source;
              length group 8 code $8;
              group=1; code='A'; stop;
            run;
            proc sql;
              create table counts as select group, code, count(*) as n
              from source group by group, code;
            quit;
            data template; group=1; code='A'; run;
            data merged; merge counts template; by group code; run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertFalse([w for step in result.steps for w in step.warnings])
        ds = sas.session.get_dataset('WORK', 'COUNTS')
        self.assertEqual(ds.metadata.get_variable('GROUP').dtype, 'numeric')
        self.assertEqual(ds.metadata.get_variable('CODE').dtype, 'character')
        self.assertEqual(sas.session.get_dataset('WORK', 'MERGED').data['group'].tolist(), [1])


if __name__ == '__main__':
    unittest.main()
