import logging
from collections import namedtuple

from lupa import LuaRuntime

logger = logging.getLogger('pychdkptp.chdkptp')

DeviceInfo = namedtuple("DeviceInfo", ('status', 'model_name', 'bus_num',
                                       'device_num', 'vendor_id', 'product_id',
                                       'serial_num'))
Message = namedtuple("Message", ('type', 'script_id', 'value'))


def _get_lua_runtime():
    runtime = LuaRuntime()
    if not runtime.eval("type(jit) == 'table'"):
        raise RuntimeError("lupa must be linked against Lua, not LuaJIT.\n"
                           "Please install lupa with `--no-luajit`.")
    # Load chdkptp modules
    runtime.execute("""
        require('chdkptp')
        util = require('util')
        util:import()
        chdku = require('chdku')
        exposure = require('exposure')
        dng = require('dng')
        prefs = require('prefs')
    """)

    # Enable debug logging
    runtime.execute("""
        prefs._add('core_verbose', 'number', 'ptp core verbosity', 0,
                   function(self) return corevar.get_verbose() end,
                   function(self,val) corevar.set_verbose(val) end)
        prefs._set('core_verbose', 2)
        prefs._set('cli_verbose', 2)
    """)

    # Register loggers
    runtime.execute("""
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
    runtime.execute("""
        con = chdku.connection()
    """)
    return runtime


def list_devices():
    """ Lists all recognized PTP devices on the USB bus.

    :return:  All connected PTP devices
    :rtype:   List of `DeviceInfo` named tuples
    """
    raise NotImplementedError


def find_devices(bus_num=None, device_num=None, serial_num=None,
                 product_id=None):
    """ Find PTP devices on the USB bus.

    :param bus_num:     Number of USB bus
    :type bus_num:      int
    :param device_num:  Number of USB device on bus
    :type device_num:   int
    :param serial_num:  Serial number of USB device
    :type serial_num:   str/unicode
    :param product_id:  USB product ID
    :type product_id:   int
    :return:            All matching PTP devices
    :rtype:             List of `DeviceInfo` named tuples
    """
    raise NotImplementedError


class ChdkDevice(object):
    def __init__(self, device_info):
        """ Create a new device instance and connect to the CHDK device.

        :param device_info:   Information about device to connect to
        :type device_info:    :class:`DeviceInfo`
        """
        self._lua = _get_lua_runtime()
        raise NotImplementedError

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

    def lua_execute(self, lua_code, wait=True):
        """ Execute Lua code on the device.

        :param lua_code:    Lua code to execute
        :type lua_code:     str/unicode
        :param wait:        Block until code has finished executing
        :type wait:         bool
        :return:            Return value of lua code, only if `wait=False`
        :rtype:             bool/int/unicode/dict/tuple
        """
        # lua
        raise NotImplementedError

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
