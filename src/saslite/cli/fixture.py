"""Create persistent dummy fixture CSV files from project metadata."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from saslite.fixtures import create_fixture, parse_dataset_reference
from saslite.project_config import discover_project_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="saslite-fixture",
        description="Create a dummy fixture CSV header from strict metadata",
    )
    parser.add_argument("dataset", help="Dataset to scaffold as LIBREF.DATASET")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root containing saslite-project.json (default: current directory)",
    )
    parser.add_argument(
        "--project-file",
        default=None,
        help="Explicit saslite-project.json path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing fixture",
    )
    args = parser.parse_args(argv)

    try:
        config = discover_project_config(
            explicit=args.project_file,
            project_root=args.project_root,
        )
        if config.path is None:
            candidate = Path(args.project_root).expanduser().resolve()
            raise FileNotFoundError(
                f"Project configuration file not found: "
                f"{candidate / 'saslite-project.json'}"
            )
        libref, member = parse_dataset_reference(args.dataset)
        library = config.library_metadata.get(libref)
        if library is None:
            raise ValueError(
                f"Strict metadata for library {libref} was not found in "
                f"{config.metadata_dir}"
            )
        schema = library.datasets.get(member)
        if schema is None:
            raise ValueError(
                f"Dataset {libref}.{member} was not found in {library.path}"
            )
        if config.fixtures_dir is None:
            raise ValueError("fixtures_dir is not configured")
        target = create_fixture(
            config.fixtures_dir,
            libref=libref,
            member=member,
            schema=schema,
            force=args.force,
        )
    except (FileExistsError, FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Created fixture: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
