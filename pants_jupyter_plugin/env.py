# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Any, Mapping


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
