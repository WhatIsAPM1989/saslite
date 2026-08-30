from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CreateSasliteProjectTests(unittest.TestCase):
    def test_generator_creates_default_structure_and_configs(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        script = repository / "scripts" / "create-saslite-project.py"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "new-project"
            completed = subprocess.run(
                [sys.executable, str(script), str(project)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((project / "saslite-project.json").is_file())
            self.assertTrue((project / "_local/config/metadata").is_dir())
            self.assertTrue((project / "_local/data/adam").is_dir())
            self.assertTrue((project / "_local/data/raw").is_dir())
            self.assertTrue((project / "_local/data/sdtm").is_dir())
            self.assertTrue((project / "_local/output/qcosi").is_dir())
            self.assertTrue((project / "_local/output/osip").is_dir())
            self.assertTrue((project / "_local/work").is_dir())
            self.assertTrue((project / "fixtures/ADAM").is_dir())
            self.assertTrue((project / "fixtures/SDTM").is_dir())

            cleaner = (
                project / "_local/config/metadata/clean-sas-log-metadata.py"
            )
            self.assertTrue(cleaner.is_file())

            config = (project / "saslite-project.json").read_text(encoding="utf-8")
            self.assertIn('"default_schema": "weak"', config)
            self.assertIn('"fixtures_dir": "fixtures"', config)

            setup = (
                project / "_local/config/localsetup.sas"
            ).read_text(encoding="utf-8")
            self.assertIn("%let saslite_data_root=", setup)
            self.assertIn('libname adam "&saslite_data_root./adam";', setup)
            self.assertIn('libname adamp "&saslite_data_root./adam";', setup)
            self.assertIn('libname sdtm "&saslite_data_root./sdtm";', setup)
            self.assertIn('libname qcosi "&saslite_output_root./qcosi";', setup)
            self.assertIn("_local/", (project / ".gitignore").read_text())

            metadata = project / "_local/config/metadata/adam.csv"
            metadata.write_text(
                "SAS log before the export\n"
                "----- BEGIN SASLITE METADATA: ADAM -----\n"
                "#SASLITE_METADATA;1;ADAM;2026-08-13T12:00:00\n"
                '"DATASET";"NAME";"TYPE";"LENGTH";"POSITION";'
                '"FORMAT";"INFORMAT";"LABEL"\n'
                "ADSL;USUBJID;character;40;1;;;Unique Subject Identifier\n"
                "\f          The SAS System          13:00 Thursday\n"
                "ADSL;AGE;numeric;8;2;BEST12.;;Age\n"
                "----- END SASLITE METADATA: ADAM -----\n"
                "NOTE: SAS log after the export\n",
                encoding="utf-8",
            )
            cleaned = subprocess.run(
                [sys.executable, str(cleaner)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
            cleaned_text = metadata.read_text(encoding="utf-8")
            self.assertNotIn("\\f", cleaned_text)
            self.assertNotIn("The SAS System", cleaned_text)
            self.assertNotIn("SAS log before", cleaned_text)
            self.assertNotIn("SAS log after", cleaned_text)
            self.assertIn("ADSL;AGE;numeric;8;2;BEST12.;;Age", cleaned_text)
            self.assertTrue(metadata.with_name("adam.csv.bak").is_file())

    def test_generator_keeps_existing_config_without_force(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        script = repository / "scripts" / "create-saslite-project.py"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            config = project / "saslite-project.json"
            config.write_text("custom\n", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(script), str(project)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), "custom\n")


if __name__ == "__main__":
    unittest.main()
