import io
import unittest
from contextlib import redirect_stderr

from saslite import SasInterpreter
from saslite.cli.main import main
from saslite.diagnostics.reporter import Reporter


class ReporterModeTests(unittest.TestCase):
    def test_forced_color_highlights_warning_and_error(self) -> None:
        log = io.StringIO()
        reporter = Reporter(stream=log, color=True)

        reporter.warning("check this")
        reporter.error("failed")
        reporter.success("completed")

        output = log.getvalue()
        self.assertIn("\033[1;33mWARNING:\033[0m check this", output)
        self.assertIn("\033[1;31mERROR:\033[0m failed", output)
        self.assertIn("\033[1;32mSUCCESS:\033[0m completed", output)

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
        self.assertIsNone(result.error)
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

    def test_runtime_warning_contains_clickable_source_location(self) -> None:
        source = """
data result;
  value=missing_source-1;
run;
"""
        sas = SasInterpreter()
        result = sas.execute(source, source_name="/tmp/program.sas")

        warning = next(
            warning for warning in result.steps[-1].warnings
            if "operator -" in warning
        )
        self.assertTrue(warning.startswith("/tmp/program.sas:3:"), warning)

    def test_execution_error_contains_clickable_source_location(self) -> None:
        log = io.StringIO()
        sas = SasInterpreter()
        sas.reporter._stream = log

        result = sas.execute(
            "\ndata result;\n  set work.absent;\nrun;\n",
            source_name="/tmp/program.sas",
        )

        self.assertFalse(result.success)
        self.assertIn(
            "ERROR: /tmp/program.sas:2:1: Dataset WORK.ABSENT does not exist",
            log.getvalue(),
        )

    def test_parse_error_contains_clickable_source_location(self) -> None:
        log = io.StringIO()
        sas = SasInterpreter()
        sas.reporter._stream = log

        result = sas.execute(
            "\ndata result;\n  value = ;\nrun;\n",
            source_name="/tmp/program.sas",
        )

        self.assertFalse(result.success)
        self.assertIn("ERROR: /tmp/program.sas:3:", log.getvalue())

    def test_quiet_cli_confirms_clean_run(self) -> None:
        log = io.StringIO()
        with redirect_stderr(log):
            exit_code = main([
                "--quiet",
                "--color", "never",
                "-e", "data result; value=1; run;",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            log.getvalue().strip(),
            "SUCCESS: Program completed without warnings or errors.",
        )

    def test_quiet_cli_does_not_report_success_after_warning(self) -> None:
        log = io.StringIO()
        with redirect_stderr(log):
            exit_code = main([
                "--quiet",
                "--color", "never",
                "-e", "data result; value=missing_source-1; run;",
            ])

        self.assertEqual(exit_code, 0)
        self.assertIn("WARNING:", log.getvalue())
        self.assertNotIn("SUCCESS:", log.getvalue())


if __name__ == "__main__":
    unittest.main()
