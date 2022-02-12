# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Optional

import pytest
from conftest import PantsRepo, other_interpreters

from pants_jupyter_plugin.pex import Pex


def test_pex_load(pex: Pex, tmpdir: Path) -> None:
    pex_file = tmpdir / "colors.pex"
    subprocess.run([str(pex.exe), "ansicolors==1.1.8", "-o", str(pex_file)], check=True)
    subprocess.run(
        args=[
            "ipython",
            "-c",
            dedent(
                f"""\
                try:
                    import colors
                    raise AssertionError(
                        "Should not have been able to import colors before loading {pex_file}."
                    )
                except ImportError:
                    # Expected.
                    pass

                %load_ext pants_jupyter_plugin
                %pex_load {pex_file}
                import colors
                """
            ),
        ],
        check=True,
    )


@pytest.mark.skipif(
    not other_interpreters(), reason="Test requires at least one other interpreter to run."
)
def test_pex_load_correct_interpreter(pex: Pex, tmpdir: Path) -> None:
    pex_file = tmpdir / "PyYAML.pex"
    subprocess.run(
        args=[
            str(pex.exe),
            "PyYAML==5.4.1",
            "--interpreter-constraint",
            "CPython>=3.6,<4",
            "-o",
            str(pex_file),
        ],
        check=True,
    )

    subprocess.run(
        args=[
            "ipython",
            "-c",
            dedent(
                f"""\
                try:
                    import yaml
                    raise AssertionError(
                        "Should not have been able to import yaml before loading {pex_file}."
                    )
                except ImportError:
                    # Expected.
                    pass

                %load_ext pants_jupyter_plugin
                %pex_load {pex_file}
                import yaml
                """
            ),
        ],
        check=True,
    )


@pytest.mark.skipif(
    not other_interpreters(), reason="Test requires at least one other interpreter to run."
)
def test_pex_load_correct_interpreter_not_available(pex: Pex, tmpdir: Path) -> None:
    pex_file = tmpdir / "PyYAML.pex"
    current_interpreter_version = ".".join(map(str, sys.version_info[:3]))
    subprocess.run(
        args=[
            str(pex.exe),
            "PyYAML==5.4.1",
            "--interpreter-constraint",
            f"CPython>=3.6,<4,!={current_interpreter_version}",
            "-o",
            str(pex_file),
        ],
        check=True,
    )

    result = subprocess.run(
        args=[
            "ipython",
            "--colors=NoColor",
            "-c",
            dedent(
                f"""\
                %load_ext pants_jupyter_plugin
                %pex_load {pex_file}
                import yaml
                """
            ),
        ],
        stdout=subprocess.PIPE,
    )
    assert result.returncode != 0

    lines = set(result.stdout.decode().splitlines())
    lines.remove(
        f"IncompatibleError: The current interpreter {sys.executable} has version "
        f"{current_interpreter_version}."
    )
    lines.remove(f"This is not compatible with the PEX at {pex_file}.")
    lines.remove(f"It has interpreter constraints CPython>=3.6,<4,!={current_interpreter_version}.")

    count = -1
    for line in list(lines):
        match = re.match(r"There are (?P<count>\d+) compatible interpreters on this system:", line)
        if match is not None:
            count = int(match.group("count"))
            lines.remove(line)
    assert count >= 0

    indexes = set(range(1, count + 1))
    interpreters = set(other_interpreters())
    assert len(interpreters) >= count
    assert len(lines) >= count
    for line in lines:
        match = re.match(r"^(?P<index>\d+)\.\) (?P<interpreter>.*)$", line)
        if match is not None:
            indexes.remove(int(match.group("index")))
            interpreters.remove(Path(match.group("interpreter")))
    assert len(indexes) == 0
    assert len(interpreters) == len(other_interpreters()) - count


def test_requirements_load() -> None:
    subprocess.run(
        args=[
            "ipython",
            "-c",
            dedent(
                f"""\
                try:
                    import colors
                    raise AssertionError(
                        "Should not have been able to import colors before loading requirements."
                    )
                except ImportError:
                    # Expected.
                    pass

                %load_ext pants_jupyter_plugin
                %requirements_load "ansicolors==1.1.8"
                import colors
                """
            ),
        ],
        check=True,
    )


def check_pants_load(
    pants_repo: PantsRepo,
    pex_target: str,
    expected_module: str,
    expected_error: Optional[str] = None,
) -> None:
    result = subprocess.run(
        args=[
            "ipython",
            "-c",
            dedent(
                f"""\
                try:
                    import {expected_module}
                    raise AssertionError(
                        "Should not have been able to import {expected_module} before loading via "
                        "{pants_repo.pants}."
                    )
                except ImportError:
                    # Expected.
                    pass

                %load_ext pants_jupyter_plugin
                %pants_repo {pants_repo.build_root}
                %pants_load {pex_target}
                import {expected_module}
                """
            ),
        ],
        stderr=subprocess.PIPE if expected_error else None,
        check=expected_error is None,
    )
    if expected_error:
        assert expected_error in result.stderr.decode()


def test_pants_v1_load(pants_v1_repo: PantsRepo) -> None:
    build_root = pants_v1_repo.build_root

    (build_root / "BUILD").write_text(
        dedent(
            f"""\
            python_requirements()

            python_binary(
                name="pkginfo-bin",
                dependencies=[
                    "//:pkginfo",
                ],
                entry_point="code:interact",
            )
            """
        )
    )
    (build_root / "requirements.txt").write_text("pkginfo==1.7.0")

    expected_error = None
    if sys.version_info[:2] >= (3, 10):
        # Pants v1 uses older Pex and creates PEX files that we cannot inspect with PEX_TOOLS using
        # Python 3.10 or newer. This should be fine in practice since Pants v1 can't in general work
        # with Python 3.10 due to using older Pex; so using Python 3.10 or newer in a notebook
        # that's meant to access Pants v1 artifacts should not be expected to work either.
        expected_error = dedent(
            """\
            No interpreter compatible with the requested constraints was found:
              Version matches >=2.7,<3.10,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*
            """
        )
    check_pants_load(
        pants_repo=pants_v1_repo,
        pex_target="//:pkginfo-bin",
        expected_module="pkginfo",
        expected_error=expected_error,
    )


def test_pants_v2_load(pants_v2_repo: PantsRepo) -> None:
    build_root = pants_v2_repo.build_root

    (build_root / "BUILD").write_text(
        dedent(
            f"""\
            python_requirements()

            pex_binary(
                name="colors-bin",
                dependencies=[
                    "//:ansicolors",
                ],
                entry_point="<none>",
            )
            """
        )
    )
    (build_root / "requirements.txt").write_text("ansicolors==1.1.8")

    check_pants_load(pants_repo=pants_v2_repo, pex_target="//:colors-bin", expected_module="colors")
