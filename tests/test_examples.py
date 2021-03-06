# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import papermill  # type: ignore
import pytest
from twitter.common.contextutil import pushd


def test_notebook_integration(input_notebook: Path, tmpdir: Path) -> None:
    output_notebook = tmpdir / f".{input_notebook.name}"
    papermill_input = str(input_notebook.resolve())
    papermill_output = str(output_notebook)
    # Execute in a pytest provided temp dir to contain any file creation in the notebook.
    with pushd(tmpdir):
        papermill.execute_notebook(papermill_input, papermill_output)
