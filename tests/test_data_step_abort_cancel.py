import unittest

from saslite import SasInterpreter


class DataStepAbortCancelTests(unittest.TestCase):
    def setUp(self):
        self.sas = SasInterpreter()
        self.sas.reporter.configure(quiet=True)

    def test_abort_preserves_log_and_cancels_later_steps(self):
        result = self.sas.execute("""
        data _null_;
          putlog 'ERROR: invalid input';
          abort cancel;
          putlog 'UNREACHABLE';
        run;
        data later; x=1; run;
        """)
        self.assertFalse(result.success)
        self.assertIn('ABORT CANCEL', result.error)
        self.assertIn('ERROR: invalid input', result.log_lines)
        self.assertNotIn('UNREACHABLE', result.log_lines)
        self.assertFalse(self.sas.session.dataset_exists('WORK', 'LATER'))

    def test_unexecuted_if_does_not_cancel(self):
        result = self.sas.execute("""
        data result; x=1; if x=2 then abort cancel; run;
        data later; x=2; run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertTrue(self.sas.session.dataset_exists('WORK', 'LATER'))

    def test_executed_if_cancels(self):
        result = self.sas.execute("data _null_; if 1 then abort cancel; run;")
        self.assertFalse(result.success)
        self.assertIn('ABORT CANCEL', result.error)

    def test_abort_in_loop_cancels(self):
        result = self.sas.execute("""
        data _null_; do i=1 to 2; if i=2 then do;
          putlog 'reached'; abort cancel;
        end; end; run;
        """)
        self.assertFalse(result.success)
        self.assertIn('reached', result.log_lines)
        self.assertIn('ABORT CANCEL', result.error)

    def test_empty_set_does_not_execute_abort(self):
        result = self.sas.execute("""
        data empty; x=1; stop; run;
        data _null_; set empty; abort cancel; run;
        data later; x=2; run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertTrue(self.sas.session.dataset_exists('WORK', 'LATER'))
