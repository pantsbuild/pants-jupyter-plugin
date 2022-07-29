# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Mapping, Iterator, Union


def create(**env_vars: Any) -> Mapping[str, str]:
    """Creates a copy of the current environment with the specified alterations.

    Keyword parameters with non-`None` values are added to the environment with the environment
    variable value being taken from the str representation of the value. Keyword parameters with
    `None` values are removed from the environment.
    """
    env = os.environ.copy()
    for name, value in env_vars.items():
        if value is not None:
            env[name] = str(value)
        else:
            env.pop(name, None)
    return env


@dataclass
class EnvManager:
    mounted: List[Path] = field(default_factory=list, hash=False)

    def unmount(self) -> Iterator[Path]:
        """Scrubs sys.path and sys.modules of any contents from previously mounted environments.

        WARNING: This will irreversibly mutate sys.path and sys.modules each time it's called.
        """
        while self.mounted:
            sys_path_entry = self.mounted.pop()
            sys.path[:] = [
                entry
                for entry in sys.path
                if entry and os.path.exists(entry) and not sys_path_entry.samefile(entry)
            ]

            for name, module in list(sys.modules.items()):
                module_path = getattr(module, "__file__", None)
                if module_path is not None:
                    if sys_path_entry in Path(module_path).parents:
                        del sys.modules[name]

            yield sys_path_entry

    def mount(self, path_parts: Iterable[Path]) -> Iterator[Path]:
        """Mounts an iterable of path parts to sys.path."""
        for path_entry in path_parts:
            sys.path.append(str(path_entry))
            self.mounted.append(path_entry)
            yield path_entry
