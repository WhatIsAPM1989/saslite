import unittest

from saslite import SasInterpreter


class ProcDatasetsOptionsTests(unittest.TestCase):
    def test_run_only_is_implicitly_terminated_by_following_data_step(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data row1; value=1; run;
            proc datasets lib=work nolist;
              delete row1;
            run;
            data after; value=2; run;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertFalse(sas.session.dataset_exists("WORK", "ROW1"))
        self.assertEqual(
            sas.get_dataset("WORK", "AFTER")["value"].tolist(),
            [2],
        )

    def test_nodetails_accepts_case_and_option_order_and_preserves_kill(self) -> None:
        for options in (
            "library=work kill nolist nodetails",
            "NoDeTaIlS lib=work nolist kill",
            "library=work nodetails kill",
        ):
            with self.subTest(options=options):
                sas = SasInterpreter()
                result = sas.execute(
                    "data old; value=1; run; "
                    f"proc datasets {options}; run; "
                    "data after; value=2; run;"
                )
                self.assertTrue(result.success, result.error)
                self.assertFalse(sas.session.dataset_exists("WORK", "OLD"))
                self.assertEqual(sas.get_dataset("WORK", "AFTER")["value"].tolist(), [2])

    def test_lib_alias_kill_and_run_quit_are_supported(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data old_one; value = 1; run;
data old_two; value = 2; run;
proc datasets lib=work nolist memtype=data kill;
run; quit;
data after_kill; value = 3; run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertFalse(sas.session.dataset_exists("WORK", "OLD_ONE"))
        self.assertFalse(sas.session.dataset_exists("WORK", "OLD_TWO"))
        self.assertTrue(sas.session.dataset_exists("WORK", "AFTER_KILL"))


if __name__ == "__main__":
    unittest.main()
