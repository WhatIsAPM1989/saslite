import unittest

from saslite import SasInterpreter


class OptionAliasTests(unittest.TestCase):
    def test_singular_option_statement_is_accepted(self) -> None:
        sas = SasInterpreter()

        result = sas.execute("option spool;")

        self.assertTrue(result.success, result.error)
        self.assertTrue(sas.session.get_option("SPOOL"))


if __name__ == "__main__":
    unittest.main()
