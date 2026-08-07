import json
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd
import pyreadstat

from saslite.runtime.dataset import Dataset
from saslite.storage.sas_backend import SasBackend


class SasBackendXptNameTests(unittest.TestCase):
    def test_stale_name_mapping_is_rejected_instead_of_silently_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = SasBackend(tmp, libref="TEST", format="xpt")
            dataset = Dataset.from_dataframe(
                pd.DataFrame({"_NAME_": ["VALUE"]}),
                name="TRANSPOSED",
                libref="TEST",
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                backend.write("TRANSPOSED", dataset)

            mapping_path = Path(tmp) / "TRANSPOSED.xpt.saslite-columns.json"
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            mapping["xpt_sha256"] = "0" * 64
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "fingerprint does not match"):
                backend.read("TRANSPOSED")

    def test_leading_underscore_column_round_trips_with_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = SasBackend(tmp, libref="TEST", format="xpt")
            dataset = Dataset.from_dataframe(
                pd.DataFrame({"_NAME_": ["VALUE"], "SASL0001": [7]}),
                name="TRANSPOSED",
                libref="TEST",
            )
            dataset.metadata.get_variable("_NAME_").label = "Source variable"

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                backend.write("TRANSPOSED", dataset)

            path = Path(tmp) / "TRANSPOSED.xpt"
            mapping_path = Path(tmp) / "TRANSPOSED.xpt.saslite-columns.json"
            self.assertTrue(mapping_path.is_file())
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            self.assertEqual(
                mapping["physical_to_logical"],
                {"SASL0002": "_NAME_"},
            )
            self.assertTrue(any("physical aliases" in str(item.message) for item in caught))

            physical, _ = pyreadstat.read_xport(str(path))
            self.assertEqual(list(physical.columns), ["SASL0002", "SASL0001"])

            restored = backend.read("TRANSPOSED")
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(list(restored.data.columns), ["_NAME_", "SASL0001"])
            self.assertEqual(restored.data.to_dict("records"), [
                {"_NAME_": "VALUE", "SASL0001": 7.0},
            ])
            self.assertEqual(
                restored.metadata.get_variable("_NAME_").label,
                "Source variable",
            )

            self.assertTrue(backend.delete("TRANSPOSED"))
            self.assertFalse(mapping_path.exists())


if __name__ == "__main__":
    unittest.main()
