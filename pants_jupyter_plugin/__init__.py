# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from .plugin import _PexEnvironmentBootstrapper


def load_ipython_extension(ipython):
  ipython.register_magics(_PexEnvironmentBootstrapper)
