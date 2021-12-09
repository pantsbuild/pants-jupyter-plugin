# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Dict, Iterator, Optional, Tuple

import pytest
from _pytest.tmpdir import TempPathFactory

from pants_jupyter_plugin import env
from pants_jupyter_plugin.pex import Pex, PexManager


def load_pex() -> Pex:
    return PexManager.load().pex


@pytest.fixture
def pex() -> Pex:
    return load_pex()


_INTERPRETER_CACHE: Dict[Pex, Tuple[Path, ...]] = {}


def interpreters(pex: Optional[Pex] = None) -> Tuple[Path, ...]:
    selected_pex: Pex = pex if pex is not None else load_pex()
    pythons = _INTERPRETER_CACHE.get(selected_pex, None)
    if pythons is None:
        output = subprocess.check_output(
            args=[str(selected_pex.exe), "interpreter", "--all", "-v"], env=env.create(PEX_TOOLS=1)
        )

        def iter_interpreters() -> Iterator[Path]:
            for line in output.decode().splitlines():
                yield Path(json.loads(line)["path"])

        _INTERPRETER_CACHE[selected_pex] = pythons = tuple(iter_interpreters())
    return pythons


def other_interpreters(pex: Optional[Pex] = None) -> Tuple[Path, ...]:
    current_interpreter = Path(sys.executable)

    def iter_other_interpreters() -> Iterator[Path]:
        for path in interpreters(pex):
            if not current_interpreter.samefile(path):
                yield path

    return tuple(iter_other_interpreters())


@dataclass(frozen=True)
class PantsRelease:
    version: str
    pex: str

    @classmethod
    def create(cls, version: str) -> "PantsRelease":
        return PantsRelease(version=version, pex=f"pants.{version}.pex")


PANTS_V1 = PantsRelease(version="1.27.0", pex="pants.1.27.0.py36.pex")
PANTS_V2 = PantsRelease.create("2.8.0")


@dataclass(frozen=True)
class PantsRepo:
    build_root: Path
    pants: Path

    @classmethod
    def create(cls, build_root: Path, pants_release: PantsRelease) -> "PantsRepo":
        url = (
            "https://github.com/pantsbuild/pants/releases/download/"
            f"release_{pants_release.version}/{pants_release.pex}"
        )
        pants_exe = Path(".pants_versions") / f"pants.{pants_release.version}.pex"
        Pex.download_once(url, pants_exe)

        pants = build_root / "pants"
        shutil.copy(pants_exe, pants)
        return cls(build_root=build_root, pants=pants)


@pytest.fixture
def pants_v2_repo(tmp_path_factory: TempPathFactory) -> PantsRepo:
    repo = PantsRepo.create(
        build_root=tmp_path_factory.mktemp(basename="repo"), pants_release=PANTS_V2
    )
    (repo.build_root / "pants.toml").write_text(
        dedent(
            f"""\
            [GLOBAL]
            backend_packages.add = [
                "pants.backend.python",
            ]
            """
        )
    )
    return repo


@pytest.fixture
def pants_v1_repo(tmp_path_factory: TempPathFactory) -> PantsRepo:
    repo = PantsRepo.create(
        build_root=tmp_path_factory.mktemp(basename="repo"), pants_release=PANTS_V1
    )
    (repo.build_root / "pants.toml").write_text(
        dedent(
            f"""\
            [GLOBAL]
            backend_packages.remove = [
                "pants.backend.codegen.antlr.java",
                "pants.backend.codegen.antlr.python",
                "pants.backend.codegen.jaxb",
                "pants.backend.codegen.ragel.java",
                "pants.backend.codegen.wire.java",
            ]
            """
        )
    )
    return repo
