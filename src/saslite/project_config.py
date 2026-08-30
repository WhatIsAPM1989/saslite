"""Load project-level SASLite configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from saslite.schema_metadata import LibrarySchema, load_metadata_directory


SCHEMA_POLICIES = {"weak", "strict"}


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Validated ``saslite-project.json`` and discovered library metadata."""

    path: Path | None = None
    version: int = 1
    default_schema: str = "weak"
    metadata_dir: Path | None = None
    fixtures_dir: Path | None = None
    library_metadata: dict[str, LibrarySchema] = field(default_factory=dict)


def load_project_config(path: str | Path) -> ProjectConfig:
    """Read project defaults and scan its metadata directory."""
    config_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in project configuration {config_path}: "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Project configuration {config_path} must contain a JSON object"
        )
    version = payload.get("version", 1)
    if version != 1:
        raise ValueError(
            f"Unsupported project configuration version {version!r} in "
            f"{config_path}; expected 1"
        )
    default_schema = _schema_policy(
        payload.get("default_schema", "weak"),
        location="default_schema",
        path=config_path,
    )
    raw_metadata_dir = payload.get("metadata_dir", "_local/config/metadata")
    if not isinstance(raw_metadata_dir, str) or not raw_metadata_dir.strip():
        raise ValueError(
            f"metadata_dir in project configuration {config_path} "
            "must be a non-empty path string"
        )
    metadata_dir = Path(raw_metadata_dir).expanduser()
    if not metadata_dir.is_absolute():
        metadata_dir = config_path.parent / metadata_dir
    metadata_dir = metadata_dir.resolve()
    library_metadata = load_metadata_directory(metadata_dir)

    raw_fixtures_dir = payload.get("fixtures_dir", "fixtures")
    if not isinstance(raw_fixtures_dir, str) or not raw_fixtures_dir.strip():
        raise ValueError(
            f"fixtures_dir in project configuration {config_path} "
            "must be a non-empty path string"
        )
    fixtures_dir = Path(raw_fixtures_dir).expanduser()
    if not fixtures_dir.is_absolute():
        fixtures_dir = config_path.parent / fixtures_dir
    fixtures_dir = fixtures_dir.resolve()

    return ProjectConfig(
        path=config_path,
        version=version,
        default_schema=default_schema,
        metadata_dir=metadata_dir,
        fixtures_dir=fixtures_dir,
        library_metadata=library_metadata,
    )


def discover_project_config(
    *,
    explicit: str | Path | None = None,
    project_root: str | Path | None = None,
) -> ProjectConfig:
    """Load an explicit config or discover ``saslite-project.json`` at a root."""
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Project configuration file not found: {path}")
        return load_project_config(path)

    if project_root is not None:
        candidate = Path(project_root).expanduser().resolve() / "saslite-project.json"
        if candidate.is_file():
            return load_project_config(candidate)

    return ProjectConfig()


def _schema_policy(value: Any, *, location: str, path: Path) -> str:
    policy = str(value).strip().lower()
    if policy not in SCHEMA_POLICIES:
        allowed = ", ".join(sorted(SCHEMA_POLICIES))
        raise ValueError(
            f"Invalid schema policy {value!r} at {location} in {path}; "
            f"expected one of: {allowed}"
        )
    return policy
