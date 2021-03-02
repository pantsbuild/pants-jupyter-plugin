Overview
========

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
