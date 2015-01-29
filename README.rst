==========
chdkptp.py
==========

Python bindings for `chdkptp <https://www.assembla.com/spaces/chdkptp/wiki>`_
via an embedded, thread-safe Lua runtime (thanks to Stefan Behnel's
`lupa <https://github.com/scoder/lupa>`_).

Requirements
============

- C compiler
- Lua 5.2, with headers
- libusb, with headers
- lupa, installed with the **--no-luajit** flag

Currently chdkptp.py only works when the ``lupa`` package is linked to
Lua. However, by default the package links to LuaJIT, so make sure that
you install it with the `--no-luajit` flag.
It is best to do this via `pip`, **before** you install chdkptp.py::

    $ pip install lupa --install-option='--no-luajit'


Documentation
=============
Please refer to the `API documentation on readthedocs.org <http://chdkptppy.readthedocs.org/en/latest/#api-reference>`_
