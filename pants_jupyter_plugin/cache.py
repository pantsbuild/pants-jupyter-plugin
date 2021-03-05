# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import xdg

DIR = Path(xdg.xdg_cache_home()) / "pants_jupyter_plugin"
