import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from saslite import SasInterpreter
from saslite.cli.main import main as cli_main
from saslite.profiles import ExampleProfile, load_profile_file


class PublicExampleProfileTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        config = root / "_local" / "config"
        output = root / "_local" / "output" / "results"
        config.mkdir(parents=True)
        output.mkdir(parents=True)
        (config / "localsetup.sas").write_text(
            "%macro localsetup;\n"
            f'  libname results "{output}";\n'
            "%mend localsetup;\n",
            encoding="utf-8",
        )
        return output

    @staticmethod
    def _source() -> str:
        return """
%bootstrap(config=%scan(example/path,1,/));
%localsetup;
data source;
  input value;
  datalines;
1
2
;
run;
%copy_for_validation(dsin=source, dsout=results.result);
"""

    def test_example_profile_is_anonymized_and_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root)
            program = root / "program.sas"
            program.write_text(self._source(), encoding="utf-8")

            sas = SasInterpreter(profile="example", profile_root=str(root))
            result = sas.execute_file(program)

            self.assertTrue(result.success, result.error)
            frame = sas.get_dataset("RESULTS", "RESULT")
            value_column = next(column for column in frame if column.upper() == "VALUE")
            self.assertEqual(frame[value_column].tolist(), [1, 2])

    def test_example_profile_can_discover_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root)
            nested = root / "programs" / "validation"
            nested.mkdir(parents=True)
            program = nested / "listing.sas"
            program.write_text(self._source(), encoding="utf-8")

            sas = SasInterpreter(profile="example")
            result = sas.execute_file(program)

            self.assertTrue(result.success, result.error)
            self.assertTrue(sas.session.dataset_exists("RESULTS", "RESULT"))

    def test_cli_accepts_example_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root)
            program = root / "program.sas"
            program.write_text(self._source(), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main(
                    [
                        "--profile",
                        "example",
                        "--profile-root",
                        str(root),
                        str(program),
                    ]
                )

            self.assertEqual(exit_code, 0, stderr.getvalue())


class ExternalProfileTests(unittest.TestCase):
    @staticmethod
    def _write_profile(path: Path) -> None:
        path.write_text(
            "from saslite.profiles import CompatibilityProfile\n"
            "class PrivateProfile(CompatibilityProfile):\n"
            "    name = 'private-test'\n"
            "    def __init__(self, project_root=None):\n"
            "        self.project_root = project_root\n"
            "    def prepare_source(self, source, *, source_name):\n"
            "        return '%let private_value=42;\\n' + source\n"
            "def create_profile(*, project_root=None):\n"
            "    return PrivateProfile(project_root)\n",
            encoding="utf-8",
        )

    def test_trusted_external_profile_file_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "project_profile.py"
            self._write_profile(profile_path)

            profile = load_profile_file(profile_path, project_root=tmp)
            self.assertEqual(profile.name, "private-test")
            self.assertEqual(profile.project_root, tmp)

            sas = SasInterpreter(profile_file=profile_path, profile_root=tmp)
            result = sas.execute("data result; value=&private_value.; run;")
            self.assertTrue(result.success, result.error)
            self.assertEqual(sas.get_dataset("WORK", "RESULT")["value"].tolist(), [42])

    def test_cli_reports_missing_external_profile_without_traceback(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = cli_main(
                ["--profile-file", "/missing/project_profile.py", "-e", "data x; run;"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("profile file not found", stderr.getvalue().lower())

    def test_named_and_file_profiles_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            SasInterpreter(profile=ExampleProfile(), profile_file="unused.py")


if __name__ == "__main__":
    unittest.main()
