Overview
========

[![PyPI Version](https://shields.io/pypi/v/pants-jupyter-plugin.svg)](https://pypi.org/project/pants-jupyter-plugin/)
[![License](https://shields.io/pypi/l/pants-jupyter-plugin.svg)](LICENSE)
[![Supported Pythons](https://shields.io/pypi/pyversions/pants-jupyter-plugin.svg)](pyproject.toml)
[![CI](https://github.com/pantsbuild/pants-jupyter-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/pantsbuild/pants-jupyter-plugin/actions/workflows/ci.yml)

This repo contains a set of Jupyter Notebook plugins that enable interop with pex and pants.

Installation
============

To install this plugin, simply invoke `pip install` like so:

```
pip install pants-jupyter-plugin
```

Plugin Loading
==============

To load the plugin in your Jupyter Notebook environment, use the `%load_ext` command in a Notebook cell like so:

```
%load_ext pants_jupyter_plugin
```

Magics
======

This package provides 3 primary magics for python environment loading from pex and/or pants targets. All of these will scrub and replace the existing sys.path/environment so it's best to do this before you import any modules to avoid cached imports.

%pex_load
---------

This magic allows you to load an existing pex file that exists on disk into the python environment. 

Usage:

```
%pex_load <path to pex file>
```

%requirements_load
------------------

This magic allows you to load a transitive closure of arbitrary requirements into the environment using pex(1).

Usage:

```
%requirements_load <requirements>
```

%pants_load
-----------

This magic allows you to build and load a pants `python_binary` target into the environment. It works in conjunction with the `%pants_repo` magic, which is how you point the plugin to a given pants-compatible repo.

```
%pants_repo <path to pants repo>
...
%pants_load <pants target>
```

Development
===========

This repo uses [tox](https://testrun.org/tox/en/latest/) for testing and project automation. To test your changes before sending them off for review just invoke tox:

```
$ tox
```

This will auto-format code and run tests. Tests accept passthough args and `pytest-xdist` is installed, so you could run the full test suite with maximum parallelism via:

```
$ tox -p -epy3{6,7,8,9} -- -n auto
```

Here you run tests against all interpreters the project supports (assuming you have these all installed on your machine and on the `$PATH`) in parallel (the tox `-p` flag) and for each parallel run of tox you run the individual test methods in parallel (via passthrough args to pytest-xdist: `-- -n auto`).

To find out all available tox environments use `tox -a` or inspect [`tox.ini`](tox.ini).
