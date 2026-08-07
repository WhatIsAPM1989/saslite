import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.runtime.dataset import Dataset


class ProcFormatCntlinTests(unittest.TestCase):
    def test_loads_numeric_and_character_formats_from_control_dataset(self) -> None:
        sas = SasInterpreter()
        control = pd.DataFrame(
            [
                {"FMTNAME": "score", "START": 0, "END": 59,
                 "LABEL": "Lower", "TYPE": "N", "HLO": ""},
                {"FMTNAME": "score", "START": 60, "END": 100,
                 "LABEL": "Higher", "TYPE": "N", "HLO": ""},
                {"FMTNAME": "score", "START": None, "END": None,
                 "LABEL": "Outside", "TYPE": "N", "HLO": "O"},
                {"FMTNAME": "state", "START": "A", "END": "A",
                 "LABEL": "Active", "TYPE": "C", "HLO": ""},
                {"FMTNAME": "state", "START": None, "END": None,
                 "LABEL": "Unknown", "TYPE": "C", "HLO": "O"},
            ]
        )
        sas.session.put_dataset(
            "WORK",
            "CONTROL",
            Dataset.from_dataframe(control, name="CONTROL"),
        )

        result = sas.execute(
            """
proc format cntlin=work.control;
run;

data rendered;
  length state $1;
  format state $state.;
  state="A";
  lower=put(10,score.);
  higher=put(75,score.);
  outside=put(150,score.);
  state_value=vvalue(state);
  unknown_state=put("X",$state.);
run;
"""
        )

        self.assertTrue(result.success, result.error)
        row = sas.get_dataset("WORK", "RENDERED").iloc[0]
        self.assertEqual(row["lower"], "Lower")
        self.assertEqual(row["higher"], "Higher")
        self.assertEqual(row["outside"], "Outside")
        self.assertEqual(row["state_value"], "Active")
        self.assertEqual(row["unknown_state"], "Unknown")

    def test_reports_missing_required_control_columns(self) -> None:
        sas = SasInterpreter()
        sas.session.put_dataset(
            "WORK",
            "BAD_CONTROL",
            Dataset.from_dataframe(
                pd.DataFrame([{"FMTNAME": "broken", "START": 1}]),
                name="BAD_CONTROL",
            ),
        )

        result = sas.execute("proc format cntlin=bad_control; run;")

        self.assertFalse(result.success)
        self.assertIn("LABEL", result.steps[-1].error or "")


if __name__ == "__main__":
    unittest.main()
