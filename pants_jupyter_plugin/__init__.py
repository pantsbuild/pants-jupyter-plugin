# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Jupyter support for Pants projects and PEX files."""  # N.B.: Flit uses this as our distribution description.

__version__ = "0.0.4"  # N.B.: Flit uses this as our distribution version.

from IPython import InteractiveShell

from .plugin import _PexEnvironmentBootstrapper


def load_ipython_extension(ipython: InteractiveShell) -> None:
    ipython.register_magics(_PexEnvironmentBootstrapper)
