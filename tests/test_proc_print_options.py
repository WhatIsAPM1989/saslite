import unittest

from saslite import SasInterpreter
from saslite.parser.program_parser import ProgramParser


class ProcPrintOptionTests(unittest.TestCase):
    def test_noobs_is_parsed_as_proc_option(self) -> None:
        program = ProgramParser().parse("proc print data=source noobs; run;")

        proc = program.steps[0]
        self.assertEqual(proc.options["DATA"], "source")
        self.assertTrue(proc.options["NOOBS"])

    def test_noobs_suppresses_observation_column(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
            data source;
              value=42;
            run;
            proc print noobs;
            run;
            """
        )

        self.assertTrue(result.success, result.error)
        output = result.steps[-1].output_messages[0]
        self.assertIn("value", output)
        self.assertIn("42", output)
        self.assertNotRegex(output, r"(?m)^\s*Obs(?:\s|$)")


if __name__ == "__main__":
    unittest.main()
