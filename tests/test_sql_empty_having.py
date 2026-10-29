import unittest

from saslite import SasInterpreter


class SqlEmptyHavingTests(unittest.TestCase):
    def test_empty_grouped_having_retains_columns(self):
        sas = SasInterpreter()
        sas.reporter.configure(quiet=True)
        result = sas.execute("""
        data source; length usubjid $8; usubjid='TEST'; stop; run;
        proc sql;
          create table duplicates as select usubjid, count(*) as records
          from source group by usubjid having count(*)>1;
        quit;
        data _null_; set duplicates; putlog usubjid= records=; run;
        """)
        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset('WORK', 'DUPLICATES')
        self.assertEqual([c.upper() for c in frame.columns], ['USUBJID', 'RECORDS'])
        self.assertEqual(len(frame), 0)
        self.assertFalse(any(step.warnings for step in result.steps))
