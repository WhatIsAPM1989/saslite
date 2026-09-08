"""SASLite - Lightweight local SAS language interpreter."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("saslite")
except PackageNotFoundError:
    __version__ = "0.5.0"

from saslite.api.facade import SasInterpreter

__all__ = ["SasInterpreter"]
