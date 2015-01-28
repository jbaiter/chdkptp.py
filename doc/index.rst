==========
chdkptp.py
==========

Python bindings for chdkptp_ via an embedded, thread-safe Lua runtime (thanks
to Stefan Behnel's lupa_).

Requirements
============
    - C compiler
    - Lua 5.2, with headers
    - libusb, with headers
    - lupa_, installed with the `--no-luajit` flag

.. _chdkptp: https://www.assembla.com/spaces/chdkptp/wiki
.. _lupa: https://github.com/scoder/lupa

API Reference
=============
.. autoclass:: chdkptp.ChdkDevice
   :members:

.. automodule:: chdkptp
   :members:

.. automodule:: chdkptp.device
   :members: Message

.. automodule:: chdkptp.lua
   :members:

.. automodule:: chdkptp.util
   :members:

Changelog
=========
0.1.1 (2015/01/28)
    - Improved user-friendliness of `lua_execute`
    - Fix bug in `download_file` where the content would not be returned if
      no local file was supplied as an argument
    - Return Python list in `list_files` instead of a Lua table



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

