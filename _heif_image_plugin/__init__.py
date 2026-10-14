"""Internal libheif bindings for HeifImagePlugin."""

# Preload bundled libheif before any submodule imports the native extension.
from . import _native  # noqa: F401
