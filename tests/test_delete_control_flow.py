import os
from pathlib import Path
import subprocess
import sys
import unittest

import pytest

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


@pytest.mark.parametrize("loop", ["while (counter<1)", "until (counter>=1)"])
@pytest.mark.parametrize("deletion", ["if x=1 then delete;", "if x=2;"])
def test_deletion_exits_condition_loop_and_resumes_next_observation(loop, deletion):
    source = f'''
from saslite import SasInterpreter
sas = SasInterpreter()
sas.reporter.configure(quiet=True)
result = sas.execute("""
    data source; x=1; output; x=2; output; run;
    data wanted; set source;
      counter=0;
      do {loop};
        {deletion}
        counter=counter+1;
      end;
      if x=1 then abort cancel;
    run;
""")
assert result.success, result.error
data = sas.get_dataset("WORK", "WANTED")
assert data.x.tolist() == [2], data
assert data.counter.tolist() == [1], data
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    completed = subprocess.run(
        [sys.executable, "-c", source], env=env,
        capture_output=True, text=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


if __name__ == "__main__":
    unittest.main()
