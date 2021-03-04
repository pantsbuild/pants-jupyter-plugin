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
import typing
from contextlib import contextmanager
from dataclasses import dataclass

import ipywidgets
import nest_asyncio
from IPython.core.magic import Magics, line_magic, magics_class
from IPython.display import Javascript, display
from pex.pex_bootstrapper import bootstrap_pex_env
from pex.variables import Variables

# TODO: replace or vendor these.
from twitter.common.contextutil import environment_as, pushd, temporary_dir

FAIL_GLYPH = "✗"
SUCCESS_GLYPH = "✓"
SPINNER_SEQ = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _scrub_import_environment(sys_modules_whitelist: typing.List[str], logger: typing.Callable):
    """Scrubs sys.path and sys.modules to a raw state.

    WARNING: This will irreversably mutate sys.path and sys.modules each time it's called.
    """
    pex_root = pathlib.Path(Variables().PEX_ROOT)

    # A generator that emits sys.path elements
    def scrubbed_sys_path():
        """Yields a scrubbed version of sys.path."""
        for p in sys.path[:]:
            if not isinstance(p, str):
                yield p

            # Scrub any/all pex locations from sys.path.
            pp = pathlib.Path(p)
            if pex_root not in pp.parents:
                yield p

    def scrub_from_sys_modules():
        """Yields keys of sys.modules as candidates for scrubbing/removal."""
        for k, m in sys.modules.items():
            if k in sys_modules_whitelist:
                continue

            if hasattr(m, "__file__") and m.__file__ is not None:
                mp = pathlib.Path(m.__file__)
                if pex_root in mp.parents:
                    yield k

    def scrub_env():
        # Replace sys.path with a scrubbed version.
        sys.path[:] = list(scrubbed_sys_path())

        # Drop module cache references from sys.modules.
        modules_to_scrub = list(scrub_from_sys_modules())
        for m in modules_to_scrub:
            del sys.modules[m]

    logger("Scrubbing sys.path and sys.modules in preparation for pex bootstrap\n")
    logger(
        f"sys.path contains {len(sys.path)} items, "
        f"sys.modules contains {len(sys.modules)} keys\n"
    )

    # Scrub environment.
    scrub_env()

    logger(
        f"sys.path now contains {len(sys.path)} items, "
        f"sys.modules now contains {len(sys.modules)} keys\n"
    )


@dataclass(frozen=True)
class _PantsRepo:
    path: pathlib.Path
    is_pants_v2: bool


@magics_class
class _PexEnvironmentBootstrapper(Magics):
    """A Magics subclass that provides pants and pex ipython magics."""

    # Capture the state of sys.modules at load time. This helps us avoid
    # scrubbing important Jupyter libraries from the running kernel.
    _ORIGINATING_SYS_MODULES_KEYS = tuple(k for k in sys.modules.keys())

    class SubprocessFailure(Exception):
        """Raised when a subprocess fails to execute."""

        def __init__(self, msg, return_code=None):
            super().__init__(msg)
            self.return_code = return_code

    class BuildFailure(SubprocessFailure):
        """Raised when a subprocess fails to execute."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pants_repo: typing.Optional[_PantsRepo] = None

    def _display_line(self, msg: str):
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

    def _append_random_id(self, base_name: str, random_id_length=5) -> str:
        random_id = "".join(random.choice(string.ascii_letters) for n in range(random_id_length))
        return f"{base_name}-{random_id}"

    @contextmanager
    def _accordion_widget(self, title, height="300px", collapsed=True):
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

        terminalStyling = (
            "<style>.%s { background-color: black;} .%s pre { color: white; }</style>"
        ) % (unique_class, unique_class)

        def set_output_glyph(glyph):
            folder.set_title(0, f"{glyph} {title}")

        def expand():
            folder.selected_index = 0

        def collapse():
            folder.selected_index = 0
            folder.selected_index = None

        layout = ipywidgets.Layout(height=height, overflow_y="scroll")
        outputter = ipywidgets.Output(layout=layout)
        outputter.add_class(unique_class)
        outputter.append_display_data(Javascript(auto_scroll_script))
        outputter.append_display_data(ipywidgets.HTML(terminalStyling))

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
            set_glyph: typing.Callable, is_complete: asyncio.Event, seq: str = SPINNER_SEQ
        ):
            spin_provider = itertools.cycle(seq)
            while not is_complete.is_set():
                set_glyph(next(spin_provider))
                await asyncio.sleep(spin_refresh_rate)

        async def async_exec(
            display: typing.Callable, cmd: str, title: str, is_complete: asyncio.Event
        ) -> int:
            p = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )

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

        def run_async(executor, spinner):
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            finished, unfinished = loop.run_until_complete(
                asyncio.wait([executor, spinner], return_when=asyncio.ALL_COMPLETED)
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
                    async_exec(self._display_line, cmd, title, is_complete),
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
            cmd = f'pex -vv -o "{output_pex}" {safe_requirements}'
            return self._stream_binary_build_with_output(cmd, title, tmp_path, extension="pex")

    def _run_pants(
        self, pants_repo: _PantsRepo, pants_target: str, extension: str
    ) -> pathlib.PosixPath:
        """Runs pants with widget UI display."""

        if pants_repo.is_pants_v2:
            goal_name = "package"
            # N.B. pants v2 doesn't support `--pants-distdir` outside of the build root.
            tmp_root = pants_repo.path.joinpath("dist")
            # N.B. The dist dir must exist for temporary_dir.
            tmp_root.mkdir(exist_ok=True)
        else:
            goal_name = "binary"
            tmp_root = None

        with temporary_dir(root_dir=tmp_root, cleanup=False) as tmp_dir:
            tmp_path = pathlib.PosixPath(tmp_dir)
            title = f"[Build] ./pants {goal_name} {pants_target}"
            cmd = (
                f'cd {pants_repo.path} && ./pants --pants-distdir="{tmp_path}" {goal_name} '
                f"{pants_target}"
            )
            return self._stream_binary_build_with_output(cmd, title, tmp_path, extension=extension)

    def _bootstrap_pex(self, pex_path: pathlib.PosixPath):
        """Bootstraps a pex with widget UI display."""
        title = f"[Bootstrap] {pex_path.name}"
        with self._accordion_widget(title) as (expand, collapse, set_output_glyph):
            try:
                with environment_as(PEX_VERBOSE="2"):
                    # Scrub the environment.
                    _scrub_import_environment(
                        self._ORIGINATING_SYS_MODULES_KEYS, self._display_line
                    )

                    # Bootstrap pex.
                    bootstrap_pex_env(pex_path)
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

    @line_magic
    def requirements_load(self, requirements: str):
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

    @line_magic
    def pex_load(self, bootstrap_pex: str):
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
        return pants_repo and pants_repo.is_dir() and pants_repo.joinpath("pants").is_file()

    @line_magic
    def pants_repo(self, pants_repo: str):
        """magic: %pants_repo: defines a pants repo path for subsequent use by %pants_load."""
        pants_repo = pants_repo.strip()
        if not pants_repo:
            self._display_line("Usage: %pants_repo <path to pants repo>\n")
            return

        pants_repo = pathlib.PosixPath(pants_repo).expanduser()
        if not self._validate_pants_repo(pants_repo):
            self._display_line(f"ERROR: could not find a valid pants repo at {pants_repo}\n")
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
                f"`pants --version` failed with:\n{version_process.stderr}",
                return_code=version_process.returncode,
            )
        version_string = version_process.stdout.decode().strip()
        is_pants_v2 = version_string.startswith("2")

        self._display_line(f"Using pants {version_string} in repo at: {pants_repo}\n")
        pants_repo = pants_repo.absolute()
        self._pants_repo = _PantsRepo(pants_repo, is_pants_v2)

    @line_magic
    def pants_load(self, pants_target: str):
        """magic: %pants_load: build and load a pants-built pex file from disk."""
        pants_target = pants_target.strip()
        if not pants_target:
            self._display_line("Usage: %pants_load <pants target>\n")
            return

        if not self._validate_pants_repo(self._pants_repo.path):
            self._display_line(
                "ERROR: could not find a valid pants repo. did you run %pants_repo "
                "<path to repo>?\n"
            )
            return

        resulting_pex = self._run_pants(self._pants_repo, pants_target, "pex")
        if not resulting_pex:
            self._display_line(
                "ERROR: Failed to produce a pex build artifact to load! See output above."
            )
            return

        self._bootstrap_pex(resulting_pex)
