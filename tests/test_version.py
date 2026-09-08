import unittest

import saslite


class VersionTests(unittest.TestCase):
    def test_runtime_version_matches_package_metadata(self) -> None:
        self.assertEqual(saslite.__version__, "0.5.0")


if __name__ == "__main__":
    unittest.main()
