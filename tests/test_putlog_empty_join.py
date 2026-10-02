import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class PutlogEmptyJoinTests(unittest.TestCase):
    def test_putlog_does_not_read_a_spurious_log_variable(self):
        for keyword in ("PUTLOG", "putlog", "PUT"):
            with self.subTest(keyword=keyword):
                sas = SasInterpreter()
                log = io.StringIO()
                sas._reporter = Reporter(stream=log)
                result = sas.execute(
                    f'data _null_; x=7; {keyword} "Check" x=; run;'
                )
                self.assertTrue(result.success, result.error)
                self.assertFalse([w for step in result.steps for w in step.warnings])
                self.assertIn("Check x=7", log.getvalue())
                self.assertNotIn("LOG", log.getvalue())

    def test_empty_complex_join_and_where_keep_selected_columns(self):
        sas = SasInterpreter()
        result = sas.execute("""
data empty;
  length id $8 visit 8 name dt $20;
  stop;
run;
proc sql;
  create table result as select distinct a.id, c.dt
  from empty as a
  inner join empty as b on a.id=b.id and
    ((not missing(a.visit) and a.visit=b.visit) or
     (missing(a.visit) and missing(b.visit) and
      not missing(a.name) and a.name=b.name))
  inner join empty as c on b.id=c.id
  where ((not missing(c.visit) and not missing(b.visit) and c.visit<=b.visit)
     or (not missing(c.dt) and lengthn(strip(c.dt))>=10 and
         substr(c.dt,1,10)<=substr(b.dt,1,10)));
quit;
""")
        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(len(frame), 0)
        self.assertEqual([c.upper() for c in frame.columns], ["ID", "DT"])


if __name__ == "__main__":
    unittest.main()
