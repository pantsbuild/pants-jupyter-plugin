# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest
import requests
from _pytest.tmpdir import TempPathFactory
from filelock import FileLock

IS_PYPY = hasattr(sys, "pypy_version_info")


@dataclass(frozen=True)
class PantsRelease:
    version: str
    pex: str

    @classmethod
    def create(cls, version: str) -> "PantsRelease":
        return PantsRelease(version=version, pex=f"pants.{version}.pex")


PANTS_V1 = PantsRelease(version="1.27.0", pex="pants.1.27.0.py36.pex")
PANTS_V2 = PantsRelease.create("2.2.0")


@dataclass(frozen=True)
class PantsRepo:
    build_root: Path
    pants: Path

    @classmethod
    def create(cls, build_root: Path, pants_release: PantsRelease) -> "PantsRepo":
        pants_exe = Path(".pants_versions") / f"pants.{pants_release.version}.pex"

        # We use the recipe here to ensure just 1 download happens across xdist workers if xdist is in
        # play: https://github.com/pytest-dev/pytest-xdist/blob/1189ae4b91c8eb2a4c81a87775a3807f9e253c68/README.rst#making-session-scoped-fixtures-execute-only-once
        if not pants_exe.exists():
            pants_exe.parent.mkdir(parents=False, exist_ok=True)
            with FileLock(f"{pants_exe}.lock"):
                if not pants_exe.exists():
                    url = (
                        "https://github.com/pantsbuild/pants/releases/download/"
                        f"release_{pants_release.version}/{pants_release.pex}"
                    )
                    download_to = pants_exe.parent / f"{pants_exe.name}.{uuid4().hex}"
                    with requests.get(url=url, stream=True) as response, download_to.open(
                        mode="wb"
                    ) as fp:
                        assert response.ok, f"GET of {url} returned {response.status_code}."
                        for chunk in response.iter_content(chunk_size=io.DEFAULT_BUFFER_SIZE):
                            fp.write(chunk)
                    assert zipfile.is_zipfile(download_to), (
                        f"The Pants PEX at {url} was downloaded to {download_to} but it does not "
                        "appear to be a valid zip file."
                    )
                    download_to.chmod(0o755)
                    download_to.rename(pants_exe)

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
