"""An anonymized example compatibility profile for local validation."""

from __future__ import annotations

import re
from pathlib import Path

from saslite.profiles.base import CompatibilityProfile, ProfileError


class ExampleProfile(CompatibilityProfile):
    """Demonstrate project setup, macro shims, and local output mapping."""

    name = "example"

    def __init__(self, project_root: str | Path | None = None) -> None:
        self._configured_root = (
            Path(project_root).expanduser().resolve() if project_root else None
        )

    def prepare_source(self, source: str, *, source_name: str) -> str:
        root = self._resolve_project_root(source_name)
        local_root = root / "_local"
        localsetup = local_root / "config" / "localsetup.sas"
        if not localsetup.is_file():
            raise ProfileError(
                "Example profile requires _local/config/localsetup.sas under "
                f"the project root: {root}"
            )

        prepared = self._remove_balanced_macro_calls(source, "bootstrap")
        prepared = self._map_shared_excel_exports(prepared, local_root)
        include_path = str(localsetup).replace('"', '""')
        prelude = "\n".join(
            [
                f'%include "{include_path}";',
                "%macro copy_for_validation(dsin=, dsout=);",
                "  data &dsout.; set &dsin.; run;",
                "%mend copy_for_validation;",
            ]
        )
        return f"{prelude}\n{prepared}"

    def _resolve_project_root(self, source_name: str) -> Path:
        if self._configured_root is not None:
            return self._configured_root

        candidates: list[Path] = []
        if not (source_name.startswith("<") and source_name.endswith(">")):
            source_path = Path(source_name).expanduser()
            candidates.extend([source_path.parent, *source_path.parent.parents])
        cwd = Path.cwd().resolve()
        candidates.extend([cwd, *cwd.parents])

        seen: set[Path] = set()
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / "_local" / "config" / "localsetup.sas").is_file():
                return candidate

        raise ProfileError(
            "Could not discover the example project root. Pass --profile-root "
            "or run a SAS file inside a project containing "
            "_local/config/localsetup.sas."
        )

    @staticmethod
    def _map_shared_excel_exports(source: str, local_root: Path) -> str:
        output_dir = local_root / "output" / "excel"
        proc_re = re.compile(
            r"\bproc\s+export\b.*?\brun\s*;",
            flags=re.IGNORECASE | re.DOTALL,
        )

        def replace(match: re.Match[str]) -> str:
            block = match.group(0)
            if not re.search(r"\bdbms\s*=\s*(?:xls|xlsx)\b", block, re.IGNORECASE):
                return block
            outfile = re.search(
                r"\boutfile\s*=\s*(['\"])/shared/exports/(?P<name>[^'\"/]+)\1",
                block,
                flags=re.IGNORECASE,
            )
            if outfile is None:
                return block
            output_dir.mkdir(parents=True, exist_ok=True)
            replacement = f'outfile="{output_dir / outfile.group("name")}"'
            return block[: outfile.start()] + replacement + block[outfile.end() :]

        return proc_re.sub(replace, source)

    @staticmethod
    def _remove_balanced_macro_calls(source: str, macro_name: str) -> str:
        call_re = re.compile(rf"%\s*{re.escape(macro_name)}\s*\(", re.IGNORECASE)
        result: list[str] = []
        cursor = 0
        search_at = 0
        while True:
            match = call_re.search(source, search_at)
            if match is None:
                result.append(source[cursor:])
                break

            open_paren = source.rfind("(", match.start(), match.end())
            depth = 1
            quote: str | None = None
            i = open_paren + 1
            while i < len(source) and depth:
                ch = source[i]
                if quote is not None:
                    if ch == quote:
                        if i + 1 < len(source) and source[i + 1] == quote:
                            i += 2
                            continue
                        quote = None
                elif ch in ("'", '"'):
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                i += 1

            if depth:
                raise ProfileError(f"Unclosed %{macro_name}(...) invocation")
            end = i
            while end < len(source) and source[end] in " \t":
                end += 1
            if end < len(source) and source[end] == ";":
                end += 1
            result.append(source[cursor : match.start()])
            result.append(f"/* EXAMPLE PROFILE: %{macro_name} supplied locally. */")
            cursor = end
            search_at = end
        return "".join(result)
