"""Built-in and external compatibility profiles."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from saslite.profiles.base import CompatibilityProfile, ProfileError
from saslite.profiles.example import ExampleProfile


def create_profile(
    name: str,
    *,
    project_root: str | None = None,
) -> CompatibilityProfile:
    """Create a public built-in compatibility profile."""
    normalized = name.strip().lower()
    if normalized == "example":
        return ExampleProfile(project_root=project_root)
    raise ValueError(f"Unknown built-in compatibility profile: {name}")


def load_profile_file(
    filename: str | Path,
    *,
    project_root: str | None = None,
) -> CompatibilityProfile:
    """Load a trusted project profile kept outside the public package.

    The module must expose ``create_profile(*, project_root=None)`` and return
    an instance of :class:`CompatibilityProfile`. Profile files execute as
    Python code and therefore must come from a trusted local source.
    """
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Compatibility profile file not found: {path}")

    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(
        f"_saslite_external_profile_{digest}",
        path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load compatibility profile: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_profile", None)
    if not callable(factory):
        raise TypeError(
            f"Compatibility profile {path} must define "
            "create_profile(*, project_root=None)"
        )

    profile = factory(project_root=project_root)
    if not isinstance(profile, CompatibilityProfile):
        raise TypeError(
            f"Compatibility profile factory in {path} returned "
            f"{type(profile).__name__}, expected CompatibilityProfile"
        )
    return profile


__all__ = [
    "CompatibilityProfile",
    "ExampleProfile",
    "ProfileError",
    "create_profile",
    "load_profile_file",
]
