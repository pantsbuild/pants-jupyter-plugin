# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
from pathlib import Path
from typing import Callable
from uuid import uuid4

import requests

from pants_jupyter_plugin.lock import creation_lock


class DownloadError(Exception):
    """Indicates an error downloading a file."""


def download_once(
    url: str, path: Path, post_process: Callable[[Path], None] = lambda _: None
) -> None:
    """Downloads a file from the given url to the given path exactly once.

    If a post_process function is given, it's passed the path of the temporary download file to
    inspect or post-process in any way seen fit except moving the file.
    """
    with creation_lock(path) as locked:
        if locked:
            download_to = path.parent / f"{path.name}.{uuid4().hex}"
            with requests.get(url=url, stream=True) as response, download_to.open(mode="wb") as fp:
                if not response.ok:
                    raise DownloadError(f"GET of {url} returned {response.status_code}.")
                for chunk in response.iter_content(chunk_size=io.DEFAULT_BUFFER_SIZE):
                    fp.write(chunk)
            post_process(download_to)
            download_to.rename(path)
