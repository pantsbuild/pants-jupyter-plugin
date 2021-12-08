# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Tuple
from uuid import uuid4

from pants_jupyter_plugin import cache, env
from pants_jupyter_plugin.download import DownloadError, download_once
from pants_jupyter_plugin.lock import creation_lock

_CACHE = cache.DIR / "pex"


@dataclass(frozen=True)
class Pex:
    exe: Path

    @staticmethod
    def download_once(url: str, download_to: Path) -> None:
        """Downloads a PEX file once.

        The PEX file will be sanity checked to at least be a zip file and made executable.
        """

        def activate_pex(path: Path) -> None:
            if not zipfile.is_zipfile(path):
                raise DownloadError(
                    f"The PEX at {url} was downloaded to {path} but it does not appear to be a "
                    "valid zip file."
                )
            path.chmod(0o755)

        download_once(url, download_to, post_process=activate_pex)

    @classmethod
    def load(cls, version: str) -> "Pex":
        url = f"https://github.com/pantsbuild/pex/releases/download/v{version}/pex"
        pex_exe = _CACHE / "exes" / f"pex-{version}.pex"
        cls.download_once(url, pex_exe)
        return cls(exe=pex_exe)


@dataclass
class PexManager:
    class IncompatibleError(Exception):
        """Indicates an incompatible PEX could not be loaded by the current interpreter."""

        def __init__(
            self,
            pex: Path,
            interpreter_constraints: Iterable[str],
            compatible_interpreters: Sequence[Path],
        ) -> None:
            version = ".".join(map(str, sys.version_info[:3]))
            compatible_interpreters_list = os.linesep.join(
                f"{index}.) {path}" for index, path in enumerate(compatible_interpreters, start=1)
            )
            super().__init__(
                dedent(
                    f"""\
                    The current interpreter {sys.executable} has version {version}.
                    This is not compatible with the PEX at {pex}.
                    It has interpreter constraints {" or ".join(interpreter_constraints)}.
                    There are {len(compatible_interpreters)} compatible interpreters on this system:
                    """
                )
                + compatible_interpreters_list
            )

    DEFAULT_VERSION = "2.1.56"
    FALLBACK_VERSION = "2.1.32"

    pex: Pex
    _fallback_pex: Optional[Pex] = None
    mounted: List[Path] = field(default_factory=list, hash=False)

    @classmethod
    def load(cls) -> "PexManager":
        return cls(pex=Pex.load(cls.DEFAULT_VERSION))

    @property
    def fallback_pex(self) -> Pex:
        if self._fallback_pex is None:
            self._fallback_pex = Pex.load(self.FALLBACK_VERSION)
        return self._fallback_pex

    def unmount(self) -> Iterator[Path]:
        """Scrubs sys.path and sys.modules of any contents from previously mounted PEXes.

        WARNING: This will irreversibly mutate sys.path and sys.modules each time it's called.
        """
        while self.mounted:
            pex_sys_path_entry = self.mounted.pop()
            sys.path[:] = [
                entry
                for entry in sys.path
                if entry and os.path.exists(entry) and not pex_sys_path_entry.samefile(entry)
            ]
            for name, module in list(sys.modules.items()):
                module_path = getattr(module, "__file__", None)
                if module_path is not None:
                    if pex_sys_path_entry in Path(module_path).parents:
                        del sys.modules[name]
            yield pex_sys_path_entry

    def mount(self, pex_to_mount: Path) -> Iterator[Path]:
        """Mounts the contents of the given PEX on the sys.path for importing."""
        current_interpreter = Path(sys.executable)

        hasher = hashlib.sha1()
        hasher.update(current_interpreter.read_bytes())
        hasher.update(pex_to_mount.read_bytes())
        fingerprint = hasher.hexdigest()

        venv = _CACHE / "venvs" / fingerprint / pex_to_mount.name
        with creation_lock(venv) as locked:
            if locked:
                pex = self.pex

                # Force the venv to select the current interpreter as the base interpreter or fail
                # if it's not compatible with constraints.
                def run_pex_tool(args: Iterable[str], **subprocess_args: Any) -> bytes:
                    return (
                        subprocess.run(
                            args=[
                                sys.executable,
                                str(pex.exe),
                                "-m",
                                "pex.tools",
                                str(pex_to_mount),
                                *args,
                            ],
                            env=env.create(PEX_INTERPRETER=1, PEX_PYTHON_PATH=sys.executable),
                            check=True,
                            **subprocess_args,
                        ).stdout
                        or b""
                    )

                pex_info = json.loads(run_pex_tool(args=["info"], stdout=subprocess.PIPE).decode())
                if "pex_hash" not in pex_info:
                    pex = self.fallback_pex

                selected_interpreter = json.loads(
                    run_pex_tool(args=["interpreter", "-v"], stdout=subprocess.PIPE).decode()
                )["path"]
                if not current_interpreter.samefile(selected_interpreter):
                    compatible_interpreters = [
                        json.loads(line)["path"]
                        for line in run_pex_tool(
                            args=["interpreter", "--all", "-v"], stdout=subprocess.PIPE
                        )
                        .decode()
                        .splitlines()
                    ]
                    interpreter_constraints = pex_info["interpreter_constraints"]
                    raise self.IncompatibleError(
                        pex_to_mount,
                        interpreter_constraints=interpreter_constraints,
                        compatible_interpreters=compatible_interpreters,
                    )
                venv_tmp = venv.parent / f"{venv.name}.{uuid4().hex}"
                run_pex_tool(args=["venv", str(venv_tmp)])
                venv_tmp.rename(venv)

        python = venv / "bin" / "python"
        result = subprocess.run(
            args=[
                str(python),
                "-c",
                "import os, site; print(os.linesep.join(site.getsitepackages()))",
            ],
            stdout=subprocess.PIPE,
            check=True,
        )
        for path in result.stdout.decode().splitlines():
            path_entry = Path(path)
            sys.path.append(path)
            self.mounted.append(path_entry)
            yield path_entry
