"""Base API for source compatibility profiles."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProfileError(RuntimeError):
    """Raised when a compatibility profile cannot be configured."""


class CompatibilityProfile(ABC):
    """Prepare environment-specific SAS source for the local runtime.

    Profiles may supply local macro libraries and path mappings, but they must
    not require callers to modify the tracked SAS program.
    """

    name: str

    @abstractmethod
    def prepare_source(self, source: str, *, source_name: str) -> str:
        """Return source augmented with the selected local environment."""
