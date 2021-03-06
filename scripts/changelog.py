import os
import subprocess
import site
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
    args=["git", "log", "--oneline", "--no-decorate", f"HEAD...{previous_tag}"],
).decode()

with open("CHANGES.md", "a") as fp:
    fp.write(
        dedent(
            """\
            ## {version}

            {changes}
            """
        ).format(version=pants_jupyter_plugin.__version__, changes=changes)
    )
