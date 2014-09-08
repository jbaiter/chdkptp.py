import logging
import numbers
import os
from collections import namedtuple

from lupa import LuaRuntime, LuaError

CHDKPTP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'vendor', 'chdkptp')

logger = logging.getLogger('pychdkptp.chdkptp')

DeviceInfo = namedtuple("DeviceInfo", ('model_name', 'bus_num', 'device_num',
                                       'vendor_id', 'product_id',
                                       'serial_num', 'chdk_api'))
Message = namedtuple("Message", ('type', 'script_id', 'value'))


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
        checked_code = "pcall(function() return {0} end)".format(lua_code)
        status, rval = self._rt.eval(checked_code)
        if not status:
            self._raise_exception(rval)
        return rval

    def pexecute(self, lua_code):
        returns = lua_code.startswith("return")
        checked_code = ("{0}pcall(function() return {1} end)"
                        .format("return " if returns else "", lua_code))
        status, rval = self._rt.execute(checked_code)
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
        self._rt = LuaRuntime(unpack_returned_tuples=True)
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
                python.eval(
                    'logger.info(\"\"\"' .. string.format(...) .. '\"\"\")'
                )
            end

            cli.dbgmsg = function(...)
                python.eval(
                    'logger.debug(\"\"\"' .. string.format(...) .. '\"\"\")'
                )
            end
        """)

        # Create global connection object
        self._rt.execute("""
            con = chdku.connection()
        """)


def list_devices():
    """ Lists all recognized PTP devices on the USB bus.

    :return:  All connected PTP devices
    :rtype:   List of `DeviceInfo` named tuples
    """
    lua = LuaContext()
    devices = lua.execute("""
    local info = {}
    local devs = chdk.list_usb_devices()
    for i, desc in ipairs(devs) do
        local lcon = chdku.connection(desc)
        lcon:connect()
        table.insert(info, {
            model_name = lcon.ptpdev.model,
            bus_num = lcon.condev.bus,
            device_num = lcon.condev.dev,
            vendor_id = lcon.condev.vendor_id,
            product_id = lcon.condev.product_id,
            serial_num = lcon.ptpdev.serial_number,
            chdk_api = lcon.apiver,
        })
        lcon:disconnect()
    end
    return info;
    """)
    infos = []
    for dev_info in devices.values():
        dev_info = dict(dev_info)
        dev_info['chdk_api'] = (dev_info['chdk_api'].MAJOR,
                                dev_info['chdk_api'].MINOR)
        infos.append(DeviceInfo(**dev_info))
    return infos


class ChdkDevice(object):
    def __init__(self, device_info):
        """ Create a new device instance and connect to the CHDK device.

        :param device_info:   Information about device to connect to
        :type device_info:    :class:`DeviceInfo`
        """
        self.info = device_info
        self._lua = LuaContext()
        self._lua.globals.devspec = self.info._asdict()
        self._lua.execute("""
        con = chdku.connection({bus = devspec.bus_num,
                                dev = devspec.device_num})
        con:connect()
        """)

    @property
    def is_connected(self):
        return self._lua.eval("con:is_connected()")

    def get_messages(self):
        """ Get all messages from device buffer

        :return:    Messages
        :rtype:     tuple of :class:`Message`
        """
        # getm
        raise NotImplementedError

    def send_message(self, message):
        """ Send a message to the device

        :param message: Message to be sent
        :type message:  str/unicode
        """
        # putm
        raise NotImplementedError

    def lua_execute(self, lua_code, wait=True, do_return=True):
        """ Execute Lua code on the device.

        :param lua_code:    Lua code to execute
        :type lua_code:     str/unicode
        :param wait:        Block until code has finished executing
        :type wait:         bool
        :do_return:         Return value of lua code, only if `wait=True`
        :rtype:             bool/int/unicode/dict/tuple
        """
        if not wait:
            self._lua.execute("con:exec('{0}'").format(lua_code)
            return None
        # NOTE: Because of the frequency of curly braces, we prefer old-style
        # string formatting in this case, since this saves us quite a bit of
        # escaping
        lua_rvals, msgs = self._lua.execute("""
        local rvals = {}
        local msgs = {}
        con:execwait('%s', {rets=rvals, msgs=msgs})
        return {rvals, msgs}
        """ % lua_code).values()
        if not do_return:
            return None
        return_values = []
        for rv in lua_rvals.values():
            # scalar
            if rv.subtype != 'table':
                return_values.append(rv.value)
                continue
            # to dict
            parsed_val = self._lua.eval(rv.value)
            parsed_val = dict(parsed_val)
            # to tuple
            if all(x.isdigit() for x in parsed_val):
                parsed_val = tuple(parsed_val.values())
            return_values.append(parsed_val)
        return (tuple(return_values)
                if len(return_values) > 1 else return_values[0])

    def kill_scripts(self, flush=True):
        """ Terminate any running script on the device.

        :param flush:   Discard script messages
        :type flush:    bool
        """
        # killscript
        raise NotImplementedError

    def upload_files(self, local_paths, remote_path='A/', skip_checks=False):
        """ Upload one or more files/directories to the device.

        :param local_paths:     One or more locals paths
        :type local_paths:      str/unicode
        :param remote_path:     Target path on the device
        :type remote_path:      str/unicode
        :param skip_checks:     Skip sanity checks on the device, required if
                                a script is running on the device while
                                uploading.
        """
        # upload, mupload
        raise NotImplementedError

    def download_files(self, remote_paths, local_path='./', skip_checks=False):
        """ Download one or more files/directories from the device.

        :param remote_paths:    One or more paths on the device. The leading
                                'A/' is optional, it will be automatically
                                prepended if not specified
        :type remote_paths:     str/unicode
        :param local_path:      Target path on the local file system
        :type local_path:       str/unicode
        :param skip_checks:     Skip sanity checks on the device, required if
                                a script is running on the device while
                                downloading.
        """
        # download, mdownload, imdl
        raise NotImplementedError

    def delete_files(self, remote_paths):
        """ Delete one or more files/directories from the device.

        :param remote_paths:    One or more paths on the device. The leading
                                'A/' is optional, it will be automatically
                                prepended if not specified
        """
        # delete, imrm
        raise NotImplementedError

    def list_files(self, remote_path='A/DCIM'):
        """ Get directory listing for a path on the device.

        :param remote_path: Path on the device
        :type remote_path:  str/unicode
        :return:            All files and directories in the path
        :rtype:             tuple of str/unicode
        """
        # ls, imls
        raise NotImplementedError

    def mkdir(self, remote_path):
        """ Create a directory on the device.
        Intermediate directories will be created as needed.

        :param remote_path: Path on the device
        :type remote_path:  str/unicode
        """
        # mkdir
        raise NotImplementedError

    def reconnect(self):
        """ Reset the connection to the device. """
        # reconnect
        raise NotImplementedError

    def reboot(self):
        """ Reboot the device. """
        # reboot
        raise NotImplementedError

    def get_frames(self, num=1, interval=0, format=None):
        """ Grab one or more frames from the device's preview viewport.

        :param num:         Number of frames to grab
        :type num:          int
        :param interval:    Interval between frames (in miliseconds)
        :type interval:     int
        :param format:      Target format for frames, if `None` the raw image
                            data is returned
        :type format:       One of None, 'jpg', 'png', 'pbm'
        :return:            Grabbed frames
        :rtype:             list of byte strings
        """
        # lvdump, lvdumpimg
        raise NotImplementedError

    def shoot(self, shutter_speed=None, real_iso=None, market_iso=None,
              aperture=None, isomode=None, nd_filter=None, distance=None,
              raw=None, dng=None, download_after=False, remove_after=False,
              stream=False):
        # shoot, remoteshoot
        raise NotImplementedError

    def switch_mode(self, mode):
        # rec, play
        raise NotImplementedError
