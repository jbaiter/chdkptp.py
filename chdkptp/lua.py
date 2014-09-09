import logging
import numbers
import os
from collections import Iterable

from lupa import LuaRuntime, LuaError

CHDKPTP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'vendor', 'chdkptp')
logger = logging.getLogger('chdkptp.lua')


class PTPError(Exception):
    def __init__(self, err_table):
        Exception.__init__(self, "{0} (ptp_code: {1}".format(err_table.msg,
                                                             err_table.ptp_rc))
        self.ptp_code = err_table.ptp_rc
        self.traceback = err_table.traceback


class LuaContext(object):
    """ Proxy object around :class:`lupa.LuaRuntime` that wraps all Lua code
        inside of `pcall` and raises proper Exceptions.
    """
    def _raise_exception(self, errval):
        if isinstance(errval, (basestring, numbers.Number)):
            raise LuaError(errval)
        elif errval['etype'] == 'ptp':
            raise PTPError(errval)
        else:
            raise LuaError(dict(errval))

    def eval(self, lua_code):
        return self._rt.eval(lua_code)

    def execute(self, lua_code):
        return self._rt.execute(lua_code)

    def peval(self, lua_code):
        returns = 'returns' in lua_code
        checked_code = ("pcall(function() {0} {1} end)"
                        .format('return' if not returns else '', lua_code))
        rval = self._rt.eval(checked_code)
        if isinstance(rval, Iterable):
            status, rval = rval
        else:
            status = rval
        if not status:
            self._raise_exception(rval)
        return rval

    def pexecute(self, lua_code):
        checked_code = ("return pcall(function() {0} end)"
                        .format(lua_code))
        rval = self._rt.execute(checked_code)
        if isinstance(rval, Iterable):
            status, rval = rval
        else:
            status = rval
        if not status:
            self._raise_exception(rval)
        return rval

    def require(self, modulename):
        return self._rt.require(modulename)

    def table(self, *items, **kwargs):
        return self._rt.table(*items, **kwargs)

    @property
    def globals(self):
        return self._rt.globals()

    def __init__(self):
        self._rt = LuaRuntime(unpack_returned_tuples=True, encoding=None)
        if self.eval("type(jit) == 'table'"):
            raise RuntimeError("lupa must be linked against Lua, not LuaJIT.\n"
                               "Please install lupa with `--no-luajit`.")
        self._setup_runtime()

    def _setup_runtime(self):
        # Set up module paths
        self._rt.execute("""
            CHDKPTP_PATH = python.eval("CHDKPTP_PATH")
            package.path = CHDKPTP_PATH .. '/lua/?.lua;' .. package.path
            package.cpath = CHDKPTP_PATH .. '/?.so;' .. package.path
        """)

        # Load chdkptp modules
        self._rt.execute("""
            require('chdkptp')
            util = require('util')
            util:import()
            varsubst = require('varsubst')
            chdku = require('chdku')
            exposure = require('exposure')
            dng = require('dng')
            prefs = require('prefs')
        """.format(CHDKPTP_PATH))

        # Enable debug logging
        self._rt.execute("""
            prefs._set('cli_verbose', 2)
        """)

        # Register loggers
        self._rt.execute("""
            cli = {}
            cli.infomsg = function(...)
                python.eval('logger.info(\"\"\"' ..
                            string.format(...):match( "(.-)%s*$" ) ..
                            '\"\"\")')
            end

            cli.dbgmsg = function(...)
                python.eval('logger.debug(\"\"\"' ..
                            string.format(...):match('(.-)%s*$') ..
                            '\"\"\")')
            end
        """)

        # Create global connection object
        self._rt.execute("""
            con = chdku.connection()
        """)


# Global Lua runtime, for use by utility functions
global_lua = LuaContext()
