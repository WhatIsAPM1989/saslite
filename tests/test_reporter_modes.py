import io
import unittest

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter


class ReporterModeTests(unittest.TestCase):
    def test_forced_color_highlights_warning_and_error(self) -> None:
        log = io.StringIO()
        reporter = Reporter(stream=log, color=True)

        reporter.warning("check this")
        reporter.error("failed")

        output = log.getvalue()
        self.assertIn("\033[1;33mWARNING: check this\033[0m", output)
        self.assertIn("\033[1;31mERROR: failed\033[0m", output)

    def test_quiet_mode_hides_notes_and_regular_output(self) -> None:
        log = io.StringIO()
        reporter = Reporter(stream=log, quiet=True)

        reporter.note("hidden")
        reporter.log("table output\nWARNING: retained warning")
        reporter.warning("visible")

        output = log.getvalue()
        self.assertNotIn("hidden", output)
        self.assertNotIn("table output", output)
        self.assertIn("WARNING: retained warning", output)
        self.assertIn("WARNING: visible", output)

    def test_fail_fast_stops_after_first_warning_step(self) -> None:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(
            stream=log,
            quiet=True,
            stop_on_error=True,
            stop_on_warning=True,
        )

        result = sas.execute(
            "data first; value=uninitialized+1; run; "
            "data should_not_run; value=1; run;"
        )

        self.assertFalse(result.success)
        self.assertIn("Stopped after warning", result.error)
        self.assertTrue(sas.session.dataset_exists("WORK", "FIRST"))
        self.assertFalse(sas.session.dataset_exists("WORK", "SHOULD_NOT_RUN"))
        self.assertEqual(log.getvalue().count("WARNING:"), 1)

    def test_fail_fast_stops_after_first_error_step(self) -> None:
        sas = SasInterpreter()
        log = io.StringIO()
        sas._reporter = Reporter(
            stream=log,
            quiet=True,
            stop_on_error=True,
            stop_on_warning=True,
        )

        result = sas.execute(
            "proc not_implemented; run; "
            "data should_not_run; value=1; run;"
        )

        self.assertFalse(result.success)
        self.assertFalse(sas.session.dataset_exists("WORK", "SHOULD_NOT_RUN"))
        self.assertEqual(log.getvalue().count("ERROR:"), 1)


if __name__ == "__main__":
    unittest.main()
