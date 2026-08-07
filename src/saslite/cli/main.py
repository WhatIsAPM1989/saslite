"""CLI main entry point for SASLite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from saslite.api.facade import SasInterpreter


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="saslite",
        description="SASLite — lightweight local SAS language interpreter",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="SAS script file to execute",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Start interactive REPL mode",
    )
    parser.add_argument(
        "-e", "--execute",
        type=str,
        help="Execute a SAS statement directly",
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default=None,
        help="Working directory for datasets (CSV storage)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["sas7bdat", "xpt"],
        default="sas7bdat",
        help="Storage format for datasets: 'sas7bdat' (default) or 'xpt'",
    )
    parser.add_argument(
        "--encoding",
        type=str,
        default="utf-8",
        help="Encoding used to read SAS script files",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version",
    )

    args = parser.parse_args(argv)

    if args.version:
        from saslite import __version__
        print(f"SASLite {__version__}")
        return 0

    sas = SasInterpreter(work_dir=args.workdir, sas_format=args.format)

    if args.execute:
        return _run_text(sas, args.execute)

    if args.file:
        return _run_file(sas, args.file, encoding=args.encoding)

    # Default: REPL mode
    return _run_repl(sas)


def _run_file(sas: SasInterpreter, filepath: str, encoding: str = "utf-8") -> int:
    """Run a SAS script file."""
    path = Path(filepath)
    if not path.exists():
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        summary = sas.execute_file(path, encoding=encoding)
    except UnicodeDecodeError as exc:
        print(
            f"ERROR: Failed to read {filepath!r} with encoding {encoding!r}: {exc}. "
            "Try --encoding latin1 or --encoding cp1252.",
            file=sys.stderr,
        )
        return 1

    if not summary.success:
        for step in summary.steps:
            if step.error:
                print(f"ERROR: {step.error}", file=sys.stderr)
        return 1

    return 0


def _run_text(sas: SasInterpreter, text: str) -> int:
    """Run a SAS statement."""
    summary = sas.execute(text)
    if not summary.success:
        for step in summary.steps:
            if step.error:
                print(f"ERROR: {step.error}", file=sys.stderr)
        return 1
    return 0


def _run_repl(sas: SasInterpreter) -> int:
    """Interactive REPL mode."""
    from saslite import __version__
    print(f"SASLite {__version__} — Interactive Mode")
    print("Type SAS statements. End each with a semicolon (;)")
    print("Type 'quit;' or 'exit;' to leave.\n")

    buffer = ""

    while True:
        try:
            if not buffer:
                prompt = "sas> "
            else:
                prompt = "...  "

            line = input(prompt)

            if line.strip().lower() in ("quit;", "exit;", "quit", "exit"):
                break

            buffer += line + "\n"

            # Check if we have a complete statement (ends with ;)
            if ";" in buffer:
                try:
                    summary = sas.execute(buffer)
                    if not summary.success:
                        for step in summary.steps:
                            if step.error:
                                print(f"ERROR: {step.error}")
                except Exception as e:
                    print(f"ERROR: {e}")
                buffer = ""

        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            buffer = ""

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
