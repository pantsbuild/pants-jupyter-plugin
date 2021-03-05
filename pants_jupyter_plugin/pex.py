# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

from pants_jupyter_plugin import cache
from pants_jupyter_plugin.download import DownloadError, download_once
from pants_jupyter_plugin.lock import creation_lock


@dataclass(frozen=True)
class Pex:
    DEFAULT_VERSION = "2.1.32"
    _CACHE = cache.DIR / "pex"

    exe: Path
    mounted: List[Path] = field(default_factory=list)

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
    def load(cls, version: Optional[str] = None) -> "Pex":
        pex_version = version or cls.DEFAULT_VERSION
        url = f"https://github.com/pantsbuild/pex/releases/download/v{pex_version}/pex"
        pex_exe = cls._CACHE / "exes" / f"pex-{pex_version}.pex"
        cls.download_once(url, pex_exe)
        return cls(exe=pex_exe)

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

    def mount_pex(self, pex_to_mount: Path) -> Iterator[Path]:
        """Mounts the contents of the given PEX on the sys.path for importing."""
        venv = (
            self._CACHE
            / "venvs"
            / hashlib.sha1(pex_to_mount.read_bytes()).hexdigest()
            / pex_to_mount.name
        )
        with creation_lock(venv) as locked:
            if locked:
                env = os.environ.copy()
                env.update(PEX_INTERPRETER="1")
                subprocess.run(
                    args=[str(self.exe), "-m", "pex.tools", str(pex_to_mount), "venv", str(venv)],
                    env=env,
                    check=True,
                )
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
