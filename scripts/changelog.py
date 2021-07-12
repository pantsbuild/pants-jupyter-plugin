import os
import site
import subprocess
import sys
from textwrap import dedent

from colors import bold, red

import pants_jupyter_plugin

previous_tag = subprocess.check_output(args=["git", "describe", "--abbrev=0"]).decode().strip()
if pants_jupyter_plugin.__version__ in previous_tag:
    version_file = pants_jupyter_plugin.__file__
    for path in site.getsitepackages():
        if version_file.startswith(path):
            version_file = os.path.relpath(version_file, path)
            break
    sys.exit(
        bold(red(f"Please increment the version in {version_file} before running this script."))
    )

changes = subprocess.check_output(
    args=[
        "git",
        "log",
        "--pretty=format:+ [%h](https://github.com/pantsbuild/pants-jupyter-plugin/commit/%h) %s",
        f"HEAD...{previous_tag}",
    ],
).decode()

with open("CHANGES.md") as fp:
    # Discard title and blank line following it.
    fp.readline()
    fp.readline()

    changelog = fp.read()

with open("CHANGES.md", "w") as fp:
    fp.write(
        dedent(
            """\
            # Release Notes

            ## {version}

            {changes}

            {changelog}
            """
        ).format(version=pants_jupyter_plugin.__version__, changes=changes, changelog=changelog)
    )
