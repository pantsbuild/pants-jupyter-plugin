from .plugin import _PexEnvironmentBootstrapper


def load_ipython_extension(ipython):
  ipython.register_magics(_PexEnvironmentBootstrapper)
