# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import asyncio
import itertools
import pathlib
import random
import shlex
import string
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Iterator, Optional, Tuple

import ipywidgets
import nest_asyncio
from IPython.core.magic import Magics, line_magic, magics_class
from IPython.display import Javascript, display

# TODO: replace or vendor these.
from twitter.common.contextutil import environment_as, temporary_dir

from pants_jupyter_plugin.pex import Pex, PexManager

FAIL_GLYPH = "✗"
SUCCESS_GLYPH = "✓"
SPINNER_SEQ = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@dataclass(frozen=True)
class _PantsRepo:
    path: pathlib.Path
    is_pants_v2: bool


@magics_class
class _PexEnvironmentBootstrapper(Magics):  # type: ignore[misc]  # IPython.core.magic is untyped.
    """A Magics subclass that provides pants and pex ipython magics."""

    # Capture the state of sys.modules at load time. This helps us avoid
    # scrubbing important Jupyter libraries from the running kernel.
    _ORIGINATING_SYS_MODULES_KEYS = tuple(k for k in sys.modules.keys())

    class SubprocessFailure(Exception):
        """Raised when a subprocess fails to execute."""

        def __init__(self, msg: str, return_code: Optional[int] = None) -> None:
            super().__init__(msg)
            self.return_code = return_code

    class BuildFailure(SubprocessFailure):
        """Raised when a subprocess fails to execute."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pex_manager = PexManager.load()
        self._pants_repo: Optional[_PantsRepo] = None

    def _display_line(self, msg: str) -> None:
        print(msg, end="", flush=True)

    def _extract_resulting_binary(
        self, build_dir: pathlib.PosixPath, extension: str
    ) -> pathlib.PosixPath:
        """Extracts exactly 1 binary from a dir and returns a Path."""
        assert build_dir.is_dir(), f"build_dir {build_dir} was not a dir!"
        # N.B. It's important we use pathlib.Path.rglob (recursive) here, since pants v2 prefixes
        # dist dirs with their address namespace.
        binaries = list(build_dir.rglob(f"*.{extension}"))
        if len(binaries) != 1:
            raise self.BuildFailure(
                "failed to select deterministic build artifact from workdir, needed 1 binary file "
                f"with extension {extension} but found {len(binaries)}. Is the BUILD target a "
                "binary (pex) output type?"
            )
        return binaries[0]

    def _append_random_id(self, base_name: str, random_id_length: int = 5) -> str:
        random_id = "".join(random.choice(string.ascii_letters) for n in range(random_id_length))
        return f"{base_name}-{random_id}"

    @contextmanager
    def _accordion_widget(
        self, title: str, height: str = "300px", collapsed: bool = True
    ) -> Iterator[Tuple[Callable[[], None], Callable[[], None], Callable[[str], None]]]:
        """Creates an Accordion widget and yields under care of its output capturer."""
        # Generate unique class for multiple invocations
        unique_class = self._append_random_id("nb-console-output")
        auto_scroll_script = """
    const config = { childList: true, subtree: true };
    const callback = function(mutationsList, observer) {
      for(let mutation of mutationsList) {
          if (mutation.type === 'childList') {
              var scrollContainer = document.querySelector(".%s");
              scrollContainer.scrollTop = scrollContainer.scrollHeight;
          }
      }
    };
    const addObserver = function() {
      const accordion = document.querySelector(".%s");
      accordion.parentElement.style.backgroundColor = "black";
      observer.observe(accordion, config);
    }
    const observer = new MutationObserver(callback);
    if (document.querySelector(".%s")) {
      addObserver();
    } else {
      // Add a small delay in case the element is not available on the DOM yet
      window.setTimeout(addObserver, 100);
    }
    """ % (
            unique_class,
            unique_class,
            unique_class,
        )

        terminal_styling = (
            "<style>"
            f".{unique_class} {{ background-color: black;}} "
            f".{unique_class} pre {{ color: white; }}"
            "</style>"
        )

        def set_output_glyph(glyph: str) -> None:
            folder.set_title(0, f"{glyph} {title}")

        def expand() -> None:
            folder.selected_index = 0

        def collapse() -> None:
            folder.selected_index = 0
            folder.selected_index = None

        layout = ipywidgets.Layout(height=height, overflow_y="scroll")
        outputter = ipywidgets.Output(layout=layout)
        outputter.add_class(unique_class)
        outputter.append_display_data(Javascript(auto_scroll_script))
        outputter.append_display_data(ipywidgets.HTML(terminal_styling))

        folder = ipywidgets.Accordion(children=[outputter])
        folder.selected_index = None if collapsed is True else 0

        set_output_glyph(" ")
        display(folder)

        # Capture the output context.
        with outputter:
            yield expand, collapse, set_output_glyph

    def _stream_binary_build_with_output(
        self,
        cmd: str,
        title: str,
        work_dir: pathlib.PosixPath,
        extension: str,
        spin_refresh_rate: float = 0.3,
    ) -> pathlib.PosixPath:
        """Runs a pex-producing command with streaming output and returns the pex location."""

        async def spin_driver(
            set_glyph: Callable[[str], None], is_complete: asyncio.Event, seq: str = SPINNER_SEQ
        ) -> None:
            spin_provider = itertools.cycle(seq)
            while not is_complete.is_set():
                set_glyph(next(spin_provider))
                await asyncio.sleep(spin_refresh_rate)

        async def async_exec(
            display: Callable[[str], None], cmd: str, is_complete: asyncio.Event
        ) -> int:
            p = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )

            # N.B.: p.stdout can technically be None and the typing is not sophisticated enough to
            # provide overloads for literals, so we simply guard the pump.
            if isinstance(p.stdout, asyncio.StreamReader):
                while True:
                    line = await p.stdout.readline()
                    if not line:
                        break
                    display(line.decode())

            try:
                return_code = await p.wait()
            finally:
                is_complete.set()

            return return_code

        def run_async(executor: Awaitable[int], spinner: Awaitable[None]) -> None:
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            tasks: Iterable[Awaitable[Any]] = [executor, spinner]
            finished, unfinished = loop.run_until_complete(
                asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
            )
            assert len(finished) == 2, f"unexpected async execution results: finished={finished}"
            assert not unfinished, f"unexpected async execution results: unfinished={unfinished}"

            results = [r for r in [task.result() for task in finished] if r is not None]
            assert len(results) == 1, f"unexpected results: {results}"
            return_code = results[0]

            if return_code != 0:
                raise self.SubprocessFailure(
                    f"command `{cmd}` failed with exit code {return_code}", return_code=return_code
                )

        with self._accordion_widget(title, collapsed=False) as (expand, collapse, set_output_glyph):
            self._display_line(f"$ {cmd}\n")
            is_complete = asyncio.Event()

            try:
                run_async(
                    async_exec(self._display_line, cmd, is_complete),
                    spin_driver(set_output_glyph, is_complete),
                )
                resulting_binary = self._extract_resulting_binary(work_dir, extension)
                self._display_line(f"\nSuccessfully built {resulting_binary}")

                set_output_glyph(SUCCESS_GLYPH)
                collapse()
                return resulting_binary
            except self.SubprocessFailure:
                try:
                    set_output_glyph(FAIL_GLYPH)
                    expand()
                    self._display_line("\n\n")
                finally:
                    raise

    def _run_pex(self, requirements: str) -> pathlib.PosixPath:
        """Runs pex with widget UI display."""
        with temporary_dir(cleanup=False) as tmp_dir:
            tmp_path = pathlib.PosixPath(tmp_dir)
            output_pex = tmp_path.joinpath("requirements.pex")
            title = f"[Resolve] {requirements}"
            safe_requirements = " ".join(shlex.quote(r) for r in shlex.split(requirements))
            # TODO: Add support for toggling `--no-pypi` and find-links/index configs.
            cmd = (
                f"{self._pex_manager.pex.exe} -vv --python {sys.executable} "
                f'-o "{output_pex}" {safe_requirements}'
            )
            return self._stream_binary_build_with_output(cmd, title, tmp_path, extension="pex")

    def _run_pants(
        self, pants_repo: _PantsRepo, pants_target: str, extension: str
    ) -> pathlib.PosixPath:
        """Runs pants with widget UI display."""

        tmp_root: Optional[str]
        if pants_repo.is_pants_v2:
            goal_name = "package"
            # N.B. pants v2 doesn't support `--pants-distdir` outside of the build root.
            dist_dir = pants_repo.path.joinpath("dist")
            # N.B. The dist dir must exist for temporary_dir.
            dist_dir.mkdir(exist_ok=True)
            tmp_root = str(dist_dir)
        else:
            goal_name = "binary"
            tmp_root = None

        with temporary_dir(root_dir=tmp_root, cleanup=False) as tmp_dir:
            title = f"[Build] ./pants {goal_name} {pants_target}"
            cmd = (
                f"cd {pants_repo.path} && ./pants --pants-distdir={tmp_dir!r} "
                f"{goal_name} {pants_target}"
            )
            tmp_path = pathlib.PosixPath(tmp_dir)
            return self._stream_binary_build_with_output(cmd, title, tmp_path, extension=extension)

    def _bootstrap_pex(self, pex_path: pathlib.PosixPath) -> None:
        """Bootstraps a pex with widget UI display."""
        title = f"[Bootstrap] {pex_path.name}"
        with self._accordion_widget(title) as (expand, collapse, set_output_glyph):
            try:
                with environment_as(PEX_VERBOSE="2"):
                    # Scrub the environment.

                    self._display_line(
                        "Scrubbing sys.path and sys.modules in preparation for pex bootstrap\n"
                    )
                    self._display_line(
                        f"sys.path contains {len(sys.path)} items, "
                        f"sys.modules contains {len(sys.modules)} keys\n"
                    )
                    for path in self._pex_manager.unmount():
                        self._display_line(f"scrubbed sys.path entry {path}\n")
                    self._display_line(
                        f"sys.path now contains {len(sys.path)} items, "
                        f"sys.modules now contains {len(sys.modules)} keys\n"
                    )

                    # Bootstrap pex.
                    for path in self._pex_manager.mount(pex_path):
                        self._display_line(f"added sys.path entry {path}\n")
            except Exception:
                try:
                    set_output_glyph(FAIL_GLYPH)
                    expand()
                finally:
                    raise
            else:
                self._display_line(f"Successfully bootstrapped pex environment from {pex_path}\n")
                set_output_glyph(SUCCESS_GLYPH)
                collapse()

    @line_magic  # type: ignore[misc]  # IPython.core.magic is untyped.
    def requirements_load(self, requirements: str) -> None:
        """magic: %requirements_load: resolve and load raw requirement specs with pex(1)."""
        if not requirements:
            self._display_line(
                "Usage: %requirements_load <requirement==version> <requirement==version> ...\n"
            )
            return

        resulting_pex = self._run_pex(requirements)
        if not resulting_pex:
            self._display_line("ERROR: Failed to resolve requirements! See output above.")
        else:
            self._bootstrap_pex(resulting_pex)

    @line_magic  # type: ignore[misc]  # IPython.core.magic is untyped.
    def pex_load(self, bootstrap_pex: str) -> None:
        """magic: %pex_load: load a pex file from disk into a running python interpreter."""
        if not bootstrap_pex or bootstrap_pex.strip() != bootstrap_pex:
            self._display_line("Usage: %pex_load <pex file>\n")
            return

        bootstrap_pex_path = pathlib.PosixPath(bootstrap_pex)
        if not bootstrap_pex_path.exists():
            self._display_line(f"ERROR: pex file `{bootstrap_pex_path}` not found")
            return

        self._bootstrap_pex(bootstrap_pex_path)

    def _validate_pants_repo(self, pants_repo: pathlib.Path) -> bool:
        """Validates a given or stored path is a valid pants repo."""
        return pants_repo.is_dir() and pants_repo.joinpath("pants").is_file()

    @line_magic  # type: ignore[misc]  # IPython.core.magic is untyped.
    def pants_repo(self, pants_repo: str) -> None:
        """magic: %pants_repo: defines a pants repo path for subsequent use by %pants_load."""
        pants_repo = pants_repo.strip()
        if not pants_repo:
            self._display_line("Usage: %pants_repo <path to pants repo>\n")
            return

        pants_repo_path = pathlib.PosixPath(pants_repo).expanduser()
        if not self._validate_pants_repo(pants_repo_path):
            self._display_line(f"ERROR: could not find a valid pants repo at {pants_repo_path}\n")
            return

        # Version check for pants v1 vs v2 flags/behavior.
        version_process = subprocess.run(
            ["./pants", "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=pants_repo,
        )
        if version_process.returncode != 0:
            raise self.SubprocessFailure(
                f"`pants --version` failed with:\n{version_process.stderr.decode()}",
                return_code=version_process.returncode,
            )
        version_string = version_process.stdout.decode().strip()
        is_pants_v2 = version_string.startswith("2")

        self._display_line(f"Using pants {version_string} in repo at: {pants_repo}\n")
        pants_repo_path = pants_repo_path.absolute()
        self._pants_repo = _PantsRepo(pants_repo_path, is_pants_v2)

    @line_magic  # type: ignore[misc]  # IPython.core.magic is untyped.
    def pants_load(self, pants_target: str) -> None:
        """magic: %pants_load: build and load a pants-built pex file from disk."""
        if self._pants_repo is None:
            self._display_line(
                "You must first specify the pants repo to load from with: "
                "%pants_repo <path to pants repo>\n"
            )
            return

        pants_target = pants_target.strip()
        if not pants_target:
            self._display_line("Usage: %pants_load <pants target>\n")
            return

        if not self._validate_pants_repo(self._pants_repo.path):
            self._display_line(
                f"ERROR: {self._pants_repo.path} does not appear to be a valid pants repo. "
                f"Check that the path is a repo with a pants script or executable.\n"
            )
            return

        resulting_pex = self._run_pants(self._pants_repo, pants_target, "pex")
        if not resulting_pex:
            self._display_line(
                "ERROR: Failed to produce a pex build artifact to load! See output above."
            )
            return

        self._bootstrap_pex(resulting_pex)
