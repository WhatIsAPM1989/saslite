import csv
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.cli.fixture import main as fixture_cli_main
from saslite.cli.main import main as cli_main
from saslite.storage.memory import MemoryBackend


class ProjectConfigTests(unittest.TestCase):
    @staticmethod
    def _write_config(
        root: Path,
        *,
        default_schema: str = "weak",
        extra: dict | None = None,
    ) -> Path:
        (root / "_local" / "config" / "metadata").mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "default_schema": default_schema,
            "metadata_dir": "_local/config/metadata",
            **(extra or {}),
        }
        path = root / "saslite-project.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @staticmethod
    def _write_metadata(
        root: Path,
        libref: str,
        rows: list[tuple[str, str, str, int, int, str, str, str]],
    ) -> Path:
        path = root / "_local" / "config" / "metadata" / f"{libref.lower()}.csv"
        buffer = io.StringIO()
        buffer.write(f"----- BEGIN SASLITE METADATA: {libref.upper()} -----\n")
        buffer.write(f"#SASLITE_METADATA;1;{libref.upper()};2026-08-12T00:00:00\n")
        writer = csv.writer(buffer, delimiter=";", quotechar='"', lineterminator="\n")
        writer.writerow([
            "DATASET", "NAME", "TYPE", "LENGTH", "POSITION",
            "FORMAT", "INFORMAT", "LABEL",
        ])
        writer.writerows(rows)
        buffer.write(f"----- END SASLITE METADATA: {libref.upper()} -----\n")
        path.write_text(buffer.getvalue(), encoding="utf-8")
        return path

    @staticmethod
    def _ae_rows() -> list[tuple[str, str, str, int, int, str, str, str]]:
        return [
            ("AE", "USUBJID", "character", 20, 1, "", "", "Subject identifier"),
            ("AE", "AETERM", "character", 200, 2, "", "", "Reported term; verbatim"),
        ]

    def test_metadata_files_discover_strict_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._write_config(root)
            self._write_metadata(root, "SDTM", self._ae_rows())

            sas = SasInterpreter(profile_root=str(root))

            self.assertEqual(sas.session.project_config_path, str(path.resolve()))
            self.assertEqual(sas.session.schema_policy, "weak")
            self.assertEqual(sas.session.schema_policy_for("ADAM"), "weak")
            self.assertEqual(sas.session.schema_policy_for("SDTM"), "strict")
            self.assertEqual(set(sas.session.library_metadata), {"SDTM"})
            metadata = sas.session.get_dataset("SDTM", "AE").metadata
            self.assertEqual(
                metadata.get_variable("AETERM").label,
                "Reported term; verbatim",
            )

    def test_weak_and_metadata_strict_libraries_have_different_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            self._write_metadata(root, "SDTM", self._ae_rows())
            sas = SasInterpreter(project_file=config)
            sas.session.storage.register("ADAM", MemoryBackend())
            sas.session.storage.register("SDTM", MemoryBackend())
            sas.create_dataset(
                "adae", pd.DataFrame({"USUBJID": ["01"]}), libref="ADAM"
            )
            sas.create_dataset(
                "ae", pd.DataFrame({"USUBJID": ["01"]}), libref="SDTM"
            )

            result = sas.execute(
                """
data weak_result;
  set adam.adae;
  weak_value=missing_adam;
run;
data strict_result;
  set sdtm.ae;
  known_value=aeterm;
  strict_value=missing_sdtm;
run;
"""
            )

            self.assertTrue(result.success, result.error)
            expectations = sas.session.schema_expectations
            self.assertEqual(len(expectations), 1)
            self.assertEqual(expectations[0].sources, ("ADAM.ADAE",))
            self.assertEqual(expectations[0].variable, "MISSING_ADAM")
            strict_warnings = "\n".join(result.steps[-1].warnings).upper()
            self.assertIn("MISSING_SDTM", strict_warnings)
            self.assertNotIn("AETERM IS UNINITIALIZED", strict_warnings)
            self.assertIn("AETERM", sas.get_dataset("WORK", "STRICT_RESULT").columns)

    def test_metadata_only_dataset_has_full_zero_row_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            self._write_metadata(root, "SDTM", self._ae_rows())
            sas = SasInterpreter(project_file=config)

            result = sas.execute("data copied; set sdtm.ae; run;")

            self.assertTrue(result.success, result.error)
            frame = sas.get_dataset("WORK", "COPIED")
            self.assertEqual(len(frame), 0)
            self.assertEqual(list(frame.columns), ["USUBJID", "AETERM"])

    def test_fixture_rows_are_overlaid_on_full_metadata_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            self._write_metadata(root, "SDTM", [
                ("AE", "USUBJID", "character", 20, 1, "", "", "Subject"),
                ("AE", "AETERM", "character", 200, 2, "", "", "Term"),
                ("AE", "AESEQ", "numeric", 8, 3, "BEST12.", "", "Sequence"),
            ])
            fixture_dir = root / "fixtures" / "sdtm"
            fixture_dir.mkdir(parents=True)
            (fixture_dir / "ae.CSV").write_text(
                "USUBJID;AESEQ\nTEST-001;1\nTEST-002;.\n",
                encoding="utf-8",
            )
            sas = SasInterpreter(project_file=config)
            sas.session.storage.register("SDTM", MemoryBackend())
            sas.create_dataset(
                "AE",
                pd.DataFrame({"USUBJID": ["PHYSICAL"], "AESEQ": [99]}),
                libref="SDTM",
            )

            frame = sas.get_dataset("SDTM", "AE")

            self.assertEqual(list(frame.columns), ["USUBJID", "AETERM", "AESEQ"])
            self.assertEqual(frame["USUBJID"].tolist(), ["TEST-001", "TEST-002"])
            self.assertEqual(frame["AETERM"].tolist(), ["", ""])
            self.assertEqual(frame.loc[0, "AESEQ"], 1)
            self.assertTrue(pd.isna(frame.loc[1, "AESEQ"]))

    def test_fixture_rejects_columns_outside_strict_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            self._write_metadata(root, "SDTM", self._ae_rows())
            fixture_dir = root / "fixtures" / "SDTM"
            fixture_dir.mkdir(parents=True)
            (fixture_dir / "AE.csv").write_text(
                "USUBJID;INVENTED\nTEST-001;value\n",
                encoding="utf-8",
            )
            sas = SasInterpreter(project_file=config)

            with self.assertRaisesRegex(ValueError, "INVENTED"):
                sas.get_dataset("SDTM", "AE")

    def test_fixture_command_scaffolds_header_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_config(root)
            self._write_metadata(root, "SDTM", self._ae_rows())
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = fixture_cli_main([
                    "SDTM.AE",
                    "--project-root",
                    str(root),
                ])

            self.assertEqual(exit_code, 0, stderr.getvalue())
            fixture = root / "fixtures" / "SDTM" / "AE.csv"
            self.assertEqual(
                fixture.read_text(encoding="utf-8"),
                "USUBJID;AETERM\n",
            )
            with redirect_stdout(stdout), redirect_stderr(stderr):
                second_exit_code = fixture_cli_main([
                    "SDTM.AE",
                    "--project-root",
                    str(root),
                ])
            self.assertEqual(second_exit_code, 1)
            self.assertIn("already exists", stderr.getvalue())

    def test_strict_policy_survives_work_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            self._write_metadata(root, "ADAM", [
                ("ADAE", "USUBJID", "character", 20, 1, "", "", "Subject"),
            ])
            sas = SasInterpreter(project_file=config)
            sas.session.storage.register("ADAM", MemoryBackend())
            sas.create_dataset(
                "adae", pd.DataFrame({"USUBJID": ["01"]}), libref="ADAM"
            )

            result = sas.execute(
                """
proc sort data=adam.adae out=adae;
  by usubjid;
run;
data result;
  set adae;
  selected=(missing_strict='Y');
run;
"""
            )

            self.assertTrue(result.success, result.error)
            self.assertFalse(sas.session.schema_expectations)
            warnings = "\n".join(result.steps[-1].warnings).upper()
            self.assertIn("MISSING_STRICT", warnings)
            self.assertIn("ADAM.ADAE", warnings)
            self.assertNotIn("INPUT DATASET(S) WORK.ADAE", warnings)

    def test_metadata_strict_policy_applies_to_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            self._write_metadata(root, "SDTM", self._ae_rows())
            sas = SasInterpreter(project_file=config)
            sas.session.storage.register("SDTM", MemoryBackend())
            sas.create_dataset(
                "ae", pd.DataFrame({"USUBJID": ["01"]}), libref="SDTM"
            )

            result = sas.execute(
                "proc sql; select missing_sql from sdtm.ae; quit;"
            )

            self.assertTrue(result.success, result.error)
            warnings = "\n".join(result.steps[-1].warnings).upper()
            self.assertIn("MISSING_SQL", warnings)
            self.assertIn("SDTM.AE", warnings)
            self.assertFalse(sas.session.schema_expectations)

    def test_cli_discovers_config_beside_program(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_config(root, default_schema="invalid")
            program = root / "program.sas"
            program.write_text("data result; value=1; run;", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main([str(program)])

            self.assertEqual(exit_code, 1)
            self.assertIn("Invalid schema policy", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
