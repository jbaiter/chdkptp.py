import logging
import numbers
import os
import re
from numbers import Number
from collections import namedtuple, Iterable

from lupa import LuaRuntime, LuaError

CHDKPTP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'vendor', 'chdkptp')
DISTANCE_RE = re.compile('(\d+(?:.\d+)?)(mm|cm|m|ft|in)')
DISTANCE_FACTORS = {
    'mm': 1,
    'cm': 100,
    'm': 1000,
    'ft': 304.8,
    'in': 25.4
}

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
global_lua = LuaContext()


def list_devices():
    """ Lists all recognized PTP devices on the USB bus.

    :return:  All connected PTP devices
    :rtype:   List of `DeviceInfo` named tuples
    """
    devices = global_lua.execute("""
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


def iso_to_av96(iso):
    return global_lua.globals.exposure.iso_to_av96(iso)


def shutter_to_tv96(shutter_speed):
    return global_lua.globals.exposure.shutter_to_tv96(shutter_speed)


def aperture_to_av96(aperture):
    return global_lua.globals.exposure.f_to_av96(aperture)


def apex_to_apex96(apex):
    x = apex*96
    return round(x) if x > 0 else -round(x)


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

    @property
    def mode(self):
        is_record, is_video, _ = self.lua_execute('return get_mode()')
        return 'record' if is_record else 'play'

    def switch_mode(self, mode):
        if mode not in ('play', 'record'):
            raise ValueError("`mode` must be one of 'play' or 'record'")
        if self.mode == mode:
            return
        mode_num = int(mode == 'record')
        status, error = self.lua_execute("""
        switch_mode_usb(%d)
        local i = 0
        while (get_mode() and 1 or 0) ~= %d and i < 300 do
            sleep(10)
            i = i + 1
        end
        if (get_mode() and 1 or 0) ~= %d then
            return false, 'switch failed'
        end
        return true, ""
        """ % (mode_num, mode_num, mode_num))
        if not status:
            raise PTPError('Could not switch mode')

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

    def lua_execute(self, lua_code, wait=True, do_return=True, remote_libs=[]):
        """ Execute Lua code on the device.

        :param lua_code:    Lua code to execute
        :type lua_code:     str/unicode
        :param wait:        Block until code has finished executing
        :type wait:         bool
        :do_return:         Return value of lua code, only if `wait=True`
        :rtype:             bool/int/unicode/dict/tuple
        """
        remote_libs = "{%s}" % ", ".join("'%s'" % lib for lib in remote_libs)
        if not wait:
            self._lua.pexecute("con:exec([[%s]], {libs=%s})"
                               % (lua_code, remote_libs))
            return None
        # NOTE: Because of the frequency of curly braces, we prefer old-style
        # string formatting in this case, since this saves us quite a bit of
        # escaping
        lua_rvals, msgs = self._lua.pexecute("""
        local rvals = {}
        local msgs = {}
        con:execwait([[%s]], {rets=rvals, msgs=msgs, libs=%s})
        return {rvals, msgs}
        """ % (lua_code, remote_libs)).values()
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
        if len(return_values) == 1:
            return return_values[0]
        else:
            return tuple(return_values)

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

    def download_file(self, remote_path, local_path=None):
        """ Download a single file from the device.

        If no local path is specified, the file's content is returned as a
        bytestring.

        :param remote_path: Path on the device. The leading 'A/' is optional,
                            it will be automatically prepended if not
                            specified
        :type remote_path:  str/unicode
        :param local_path:  (Optional) local path to store file under.
        :type local_path:   str/unicode
        :return:            If `local_path` was not specified, the file content
                            as a bytestring, otherwise None
        :rtype:             str/None
        """
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

    def _validate_shoot_args(self, **kwargs):
        for arg in ('shutter_speed', 'real_iso', 'market_iso', 'aperture',
                    'isomode'):
            if kwargs.get(arg, None) is not None and not isinstance(
                    kwargs.get(arg, None), Number):
                raise ValueError("`{0}` must be an number".format(arg))
        if sum(1 for x in ('real_iso', 'market_iso', 'isomode')
               if kwargs.get(x, None) is not None) > 1:
            raise ValueError("Only one of `real_iso`, `market_iso` or "
                             "`isomode` can be set.")
        if kwargs.get('nd_filter', None) not in (True, False, None):
            raise ValueError("`nd_filter` must be one of True (swung in), "
                             "False (swung out) or None (camera default)")
        bad_distance = (
            'distance' in kwargs
            and not (isinstance(kwargs.get('distance', None), Number)
                     or DISTANCE_RE.match(kwargs.get('distance', None))))
        if bad_distance:
            raise ValueError("`distance` must be an integer (= value in "
                             "milimeter) or a string with a suffix that is "
                             "either `m`, `cm`, `mm`, `ft` or `in`.")
        action_after = any(kwargs.get(x, False) for x in
                           ('stream', 'download_after', 'remove_after'))
        if not kwargs.get('wait', True) and action_after:
            raise ValueError("Cannot stream, remove/download after when "
                             "`wait` is `False`")

    def _parse_shoot_args(self, **kwargs):
        options = {}
        if kwargs.get('aperture', None) is not None:
            options['av'] = kwargs.get('aperture', None)
        if kwargs.get('real_iso', None) is not None:
            options['sv'] = kwargs.get('real_iso', None)
        if kwargs.get('market_iso', None) is not None:
            options['svm'] = kwargs.get('market_iso', None)
        if kwargs.get('isomode', None) is not None:
            options['isomode'] = int(kwargs.get('isomode', None))
        if kwargs.get('shutter_speed', None) is not None:
            options['tv'] = kwargs.get('shutter_speed', None)
        if kwargs.get('nd_filter', None):
            options['nd'] = 1 if kwargs.get('nd_filter', None) else 2
        if kwargs.get('distance', None) is not None:
            if not isinstance(kwargs.get('distance', None), Number):
                value, unit = DISTANCE_RE.match(
                    kwargs.get('distance', None)).groups()
                options['sd'] = round(DISTANCE_FACTORS[unit]*float(value))
            else:
                options['sd'] = round(kwargs.get('distance', None))
        if kwargs.get('dng', False):
            options['dng'] = 1
        if kwargs.get('dng', False) or kwargs.get('raw', False):
            options['raw'] = 1
        if kwargs.get('stream', True):
            if kwargs.get('dng', False):
                options['fformat'] = 6
            elif kwargs.get('raw', False):
                options['fformat'] = 4
            else:
                options['fformat'] = 1
        return options

    def shoot(self, **kwargs):
        """ Shoot a picture

        For all arguments where `None` is a legal type, it signifies that the
        current value from the camera should be used and not be overriden.

        :param shutter_speed:   Shutter speed in APEX96 (default: None)
        :type shutter_speed:    int/float/None
        :param real_iso:        Canon 'real' ISO (default: None)
        :type real_iso:         int/float/None
        :param market_iso:      Canon 'market' ISO (default: None)
        :type market_iso:       int/float/None
        :param aperture:        Aperture value in APEX96 (default: None)
        :type aperture:         int/float/None
        :param isomode:         Must conform to ISO value in Canon UI, shooting
                                mode must have manual ISO (default: None)
        :type isomode:          int/None
        :param nd_filter:       Toggle Neutral Density filter (default: None)
        :type nd_filter:        boolean/None
        :param distance:        Subject distance. If specified as an integer,
                                the value is interpreted as the distance in
                                milimeters. You can also pass a string that
                                contains a number followed by one of the
                                following units: 'mm', 'cm', 'm', 'ft' or 'in'
                                (default: None)
        :type distance:         str/unicode/int
        :param raw:             Dump raw framebuffer (default: False)
        :type raw:              boolean
        :param dng:             Dump raw framebuffer in DNG format
                                (default: False)
        :type dng:              boolean
        :param wait:            Wait for capture to complete (default: True)
        :type wait;             boolean
        :param download_after:  Download and return image data after capture
                                (default: False)
        :type download_after:   boolean
        :param remove_after:    Remove image data after shooting
                                (default: False)
        :type remove_after:     boolean
        :param stream:          Stream and return image data directly from
                                device (will not be saved on camera storage)
                                (default: True)
        :type stream:           boolean
        """
        self._validate_shoot_args()
        options = self._lua.globals.util.serialize(
            self._lua.table(**self._parse_shoot_args(**kwargs)))

        if not kwargs.get('wait', True):
            self.lua_execute("rlib_shoot(%s)" % options, wait=False,
                             remote_libs=['rlib_shoot'])
            return
        if not kwargs.get('stream', True):
            status, errors = self.lua_execute(
                "return rlib_shoot(%s)" % options,
                remote_libs=['serialize_msgs', 'rlib_shoot'])
            # TODO: Check for errors
            if not (kwargs.get('download_after', False) or
                    kwargs.get('remove_after', False)):
                return

            # TODO: Construct path on device for captured image
            img_path = ''
            rval = None
            if kwargs.get('download_after', False):
                rval = self.download_file(img_path)
            if kwargs.get('remove_after', False):
                self.delete_files((img_path,))
            return rval
        else:
            self.lua_execute(
                "return rs_init(%s)" % options, remote_libs=['rs_shoot_init'])
            # TODO: Check for errors
            self.lua_execute("rs_shoot(%s)" % options,
                             remote_libs=['rs_shoot'], wait=False)
            rcopts = {}
            img_data = self._lua.table()
            if kwargs.get('dng', False) and not kwargs.get('raw', False):
                dng_info = self._lua.table(lstart=0, lcount=0, badpix=0)
                rcopts['dng_hdr'] = self._lua.globals.chdku.rc_handler_store(
                    self._lua.eval("""
                    function(dng_info)
                        return function(chunk)
                            dng_info.hdr=chunk.data
                        end
                    end
                    """)(dng_info))
                rcopts['raw'] = self._lua.eval("""
                    function(dng_info, img_data)
                        return function(lcon, hdata)
                            cli.dbgmsg('rc chunk get %d\\n', hdata.id)
                            local status, raw = lcon:capture_get_chunk_pcall(
                                hdata.id)
                            if not status then
                                return false, raw
                            end
                            cli.dbgmsg('rc chunk size:%d offset:%s last:%s\\n',
                                       raw.size, tostring(raw.offset),
                                       tostring(raw.last))
                            table.insert(img_data, {data=dng_info.hdr})
                            local status, err = chdku.rc_process_dng(dng_info,
                                                                    raw)
                            if status then
                                table.insert(img_data, {data=dng_info.thumb})
                                table.insert(img_data, raw)
                            end
                            return status, err
                        end
                    end
                    """)(dng_info, img_data)
            else:
                rcopts['jpg'] = self._lua.globals.chdku.rc_handler_store(
                    img_data)
            self._lua.globals.con.capture_get_data_pcall(
                self._lua.globals.con, self._lua.table(**rcopts))
            self._lua.globals.con.wait_status_pcall(
                self._lua.globals.con,
                self._lua.table(run=False, timeout=30000))
            # TODO: Check for error
            # TODO: Check for timeout
            self.lua_execute('init_usb_capture(0)')
            # NOTE: We can't touch the chunk data from Python or else the
            # Lua runtime segfaults, so we let Lua take care of assembling
            # the output data
            return self._lua.eval("""
                function(chunks)
                    local out_data = ''
                    for i, c in ipairs(chunks) do
                        out_data = out_data .. c.data:string()
                    end
                    return out_data
                end
                """)(img_data)
            return img_data
