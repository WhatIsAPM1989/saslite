import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class SqlOutobsTests(unittest.TestCase):
    def _interpreter_with_source(self) -> tuple[SasInterpreter, io.StringIO]:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(stream=log)
        result = sas.execute(
            """
            data source;
                input id group $ value;
            datalines;
            1 A 10
            2 A 20
            3 B 30
            4 B 40
            ;
            run;
            """
        )
        self.assertTrue(result.success, result.error)
        log.seek(0)
        log.truncate(0)
        return sas, log

    def test_outobs_limits_displayed_select_after_ordering(self) -> None:
        sas, log = self._interpreter_with_source()

        result = sas.execute(
            """
            proc sql noprint outobs=2;
                select id, value from source order by id desc;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.steps[-1].rows_affected, 2)
        output = log.getvalue()
        self.assertIn("PROC SQL: 2 rows selected", output)
        self.assertIn("40", output)
        self.assertIn("30", output)
        self.assertNotIn("10", output)

    def test_outobs_limits_created_table(self) -> None:
        sas, _log = self._interpreter_with_source()

        result = sas.execute(
            """
            proc sql outobs=2;
                create table highest as
                select id, value from source order by value desc;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "HIGHEST")
        self.assertEqual(frame["ID"].tolist(), [4, 3])
        self.assertEqual(frame["VALUE"].tolist(), [40, 30])

    def test_outobs_limits_grouped_query_result(self) -> None:
        sas, _log = self._interpreter_with_source()

        result = sas.execute(
            """
            proc sql outobs=1;
                create table group_counts as
                select group, count(*) as n
                from source
                group by group
                order by group desc;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "GROUP_COUNTS")
        self.assertEqual(frame["group"].tolist(), ["B"])
        self.assertEqual(frame["n"].tolist(), [2])


if __name__ == "__main__":
    unittest.main()
