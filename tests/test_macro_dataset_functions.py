import io
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class MacroDatasetFunctionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sas = SasInterpreter()
        self.log = io.StringIO()
        self.sas._reporter = Reporter(stream=self.log)
        self.sas.create_dataset(
            "subjects",
            pd.DataFrame(
                {
                    "StudyID": ["ABC", "ABC"],
                    "Age": [34, 51],
                }
            ),
        )
        study_id = self.sas.session.get_dataset(
            "WORK", "SUBJECTS"
        ).metadata.get_variable("StudyID")
        self.assertIsNotNone(study_id)
        study_id.label = "Study identifier"

    def test_open_handle_survives_execute_calls_and_exposes_metadata(self) -> None:
        opened = self.sas.execute(
            "%let dsid=%sysfunc(open(work.subjects,i));"
        )
        inspected = self.sas.execute(
            "%put "
            "DSID=&dsid "
            "VARNUM=%sysfunc(varnum(&dsid,age)) "
            "VARNAME=%sysfunc(varname(&dsid,1)) "
            "VARTYPE=%sysfunc(vartype(&dsid,2)) "
            "VARLABEL=%sysfunc(varlabel(&dsid,1)) "
            "NOBS=%sysfunc(attrn(&dsid,nobs)) "
            "NVARS=%sysfunc(attrn(&dsid,nvars));"
        )

        self.assertTrue(opened.success, opened.error)
        self.assertTrue(inspected.success, inspected.error)
        self.assertEqual(
            self.log.getvalue(),
            "DSID=1 VARNUM=2 VARNAME=StudyID VARTYPE=N "
            "VARLABEL=Study identifier NOBS=2 NVARS=2\n",
        )

    def test_open_defaults_one_level_names_to_work(self) -> None:
        result = self.sas.execute(
            "%put DSID=%sysfunc(open(subjects)) "
            "MISSING=%sysfunc(open(does_not_exist));"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(self.log.getvalue(), "DSID=1 MISSING=0\n")

    def test_exist_checks_one_and_two_level_dataset_names(self) -> None:
        result = self.sas.execute(
            "%put ONE=%sysfunc(exist(subjects)) "
            "TWO=%sysfunc(exist(work.subjects)) "
            "OPTIONS=%sysfunc(exist(work.subjects(where=(age > 40)))) "
            "MISSING=%sysfunc(exist(work.absent));"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            self.log.getvalue(),
            "ONE=1 TWO=1 OPTIONS=1 MISSING=0\n",
        )

    def test_data_step_exist_uses_the_same_session_datasets(self) -> None:
        result = self.sas.execute(
            """
            data existence_flags;
                present = exist("work.subjects");
                absent = exist("work.absent");
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        frame = self.sas.get_dataset("WORK", "EXISTENCE_FLAGS")
        self.assertEqual(frame.loc[0, "present"], 1)
        self.assertEqual(frame.loc[0, "absent"], 0)

    def test_varnum_is_case_insensitive_and_returns_zero_when_absent(self) -> None:
        self.assertTrue(
            self.sas.execute("%let dsid=%sysfunc(open(subjects));").success
        )
        result = self.sas.execute(
            "%put LOWER=%sysfunc(varnum(&dsid,studyid)) "
            "ABSENT=%sysfunc(varnum(&dsid,unknown));"
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(self.log.getvalue(), "LOWER=1 ABSENT=0\n")

    def test_close_invalidates_handle(self) -> None:
        self.assertTrue(
            self.sas.execute("%let dsid=%sysfunc(open(subjects));").success
        )
        closed = self.sas.execute("%put RC=%sysfunc(close(&dsid));")
        inspected = self.sas.execute(
            "%put NAME=%sysfunc(varname(&dsid,1)) "
            "RC2=%sysfunc(close(&dsid));"
        )

        self.assertTrue(closed.success, closed.error)
        self.assertTrue(inspected.success, inspected.error)
        self.assertEqual(self.log.getvalue(), "RC=0\nNAME= RC2=1\n")

    def test_unknown_sysfunc_returns_failed_summary_without_raising(self) -> None:
        result = self.sas.execute("%put %sysfunc(no_such_function(1));")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Unknown function: no_such_function")
        self.assertEqual(
            self.log.getvalue(),
            "ERROR: Unknown function: no_such_function\n",
        )


if __name__ == "__main__":
    unittest.main()
