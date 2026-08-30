#!/usr/bin/env python3
"""Create a SASLite dummy fixture from project metadata."""

import os
from pathlib import Path
import sys


# Keep the checkout script usable before an editable install, like
# ``scripts/run-saslite``.
repository_root = Path(__file__).resolve().parents[1]
venv_python = repository_root / ".venv" / "bin" / "python"
if (
    venv_python.is_file()
    and Path(sys.executable).resolve() != venv_python.resolve()
):
    os.execv(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )
sys.path.insert(0, str(repository_root / "src"))

from saslite.cli.fixture import main


if __name__ == "__main__":
    raise SystemExit(main())
