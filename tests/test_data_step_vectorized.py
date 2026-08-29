import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from saslite import SasInterpreter
from saslite.executor.data_step.executor import DataStepExecutor
from saslite.runtime.dataset import Dataset


class VectorizedDataStepTests(unittest.TestCase):
    @staticmethod
    def _interpreter(frame: pd.DataFrame) -> SasInterpreter:
        sas = SasInterpreter()
        sas.session.put_dataset(
            "WORK",
            "SOURCE",
            Dataset.from_dataframe(frame, "SOURCE"),
        )
        return sas

    def test_simple_numeric_step_bypasses_row_executor(self) -> None:
        sas = self._interpreter(pd.DataFrame({"ID": range(6), "X": range(6)}))

        with patch.object(
            DataStepExecutor,
            "_execute_statements",
            side_effect=AssertionError("row executor was used"),
        ):
            result = sas.execute(
                "data out; set source; y=x*2+1; if x>=3; keep id y; run;"
            )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "OUT").to_dict("records"),
            [
                {"ID": 3, "y": 7.0},
                {"ID": 4, "y": 9.0},
                {"ID": 5, "y": 11.0},
            ],
        )

    def test_conditions_missing_functions_and_n_match_row_engine(self) -> None:
        frame = pd.DataFrame({"ID": [1, 2, 3, 4], "X": [0.0, 1.0, 2.0, np.nan]})
        source = """
            data out;
              set source;
              observation=_n_;
              total=sum(x, 10);
              missing_count=nmiss(x);
              if missing(x) then band=0;
              else if x>=1 then band=2;
              else band=1;
              if x ne 2;
            run;
        """

        fast = self._interpreter(frame)
        fast_result = fast.execute(source)
        self.assertTrue(fast_result.success, fast_result.error)

        slow = self._interpreter(frame)
        with patch.object(
            DataStepExecutor,
            "_vectorized_step_is_eligible",
            return_value=False,
        ):
            slow_result = slow.execute(source)
        self.assertTrue(slow_result.success, slow_result.error)

        pd.testing.assert_frame_equal(
            fast.get_dataset("WORK", "OUT"),
            slow.get_dataset("WORK", "OUT"),
            check_dtype=False,
        )
        self.assertEqual(fast_result.steps[-1].warnings, slow_result.steps[-1].warnings)

    def test_missing_arithmetic_uses_row_engine_and_preserves_warning(self) -> None:
        sas = self._interpreter(pd.DataFrame({"X": [1.0, np.nan]}))
        original = DataStepExecutor._execute_statements
        calls: list[int] = []

        def tracked(executor, statements, context):
            calls.append(1)
            return original(executor, statements, context)

        with patch.object(DataStepExecutor, "_execute_statements", tracked):
            result = sas.execute("data out; set source; y=x+1; run;")

        self.assertTrue(result.success, result.error)
        self.assertTrue(calls)
        self.assertTrue(
            any("Missing value generated" in warning for warning in result.steps[-1].warnings)
        )

    def test_character_overflow_uses_row_engine_and_preserves_warning(self) -> None:
        sas = self._interpreter(pd.DataFrame({"CODE": ["ABCDE", "LONGER"]}))
        result = sas.execute("data out; length code $3; set source; run;")

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(result.steps[-1].warnings), 1)
        self.assertIn("Character truncation risk", result.steps[-1].warnings[0])


if __name__ == "__main__":
    unittest.main()
