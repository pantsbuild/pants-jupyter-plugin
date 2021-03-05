# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from filelock import FileLock


@contextmanager
def creation_lock(path: Path) -> Iterator[Optional[str]]:
    """A context manager that yields a creation lock if the given path does not exist.

    The lock should be considered an opaque token. If its not None, the file does not exist and the
    lock to create the file has been acquired. If it is None, the file was already created.

    This is a blocking lock but otherwise safe lock.
    """
    if path.exists():
        yield None
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = f"{path}.lock"
    with FileLock(lock_file):
        yield None if path.exists() else lock_file
