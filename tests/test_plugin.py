# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from pathlib import Path
from textwrap import dedent

import pytest
from conftest import PantsRepo


def test_pex_load(tmpdir: Path) -> None:
    pex_file = tmpdir / "colors.pex"
    subprocess.run(["pex", "ansicolors==1.1.8", "-o", pex_file], check=True)
    subprocess.run(
        [
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


def test_requirements_load() -> None:
    subprocess.run(
        [
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


def check_pants_load(pants_repo: PantsRepo, pex_target: str, expected_module: str) -> None:
    subprocess.run(
        [
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
        check=True,
    )


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

    check_pants_load(
        pants_repo=pants_v1_repo, pex_target="//:pkginfo-bin", expected_module="pkginfo"
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
