"""Atomberg IoT fan CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fancli")
except PackageNotFoundError:
    # Local source checkout without installed package metadata.
    __version__ = "0.0.0+dev"
