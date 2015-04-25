import os
import re
import StringIO
import tempfile
from collections import namedtuple
from numbers import Number

from chdkptp.lua import LuaContext, PTPError, global_lua, parse_table
import chdkptp.util as util

from lupa import LuaError


DISTANCE_RE = re.compile('(\d+(?:.\d+)?)(mm|cm|m|ft|in)')
DISTANCE_FACTORS = {
    'mm': 1,
    'cm': 100,
    'm': 1000,
    'ft': 304.8,
    'in': 25.4
}

Message = namedtuple("Message", ('type', 'script_id', 'value'))
DeviceInfo = namedtuple("DeviceInfo", ('model_name', 'bus_num', 'device_num',
                                       'vendor_id', 'product_id',
                                       'serial_num', 'chdk_api'))


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


class ChdkDevice(object):
    def __init__(self, device_info):
        """ Create a new device instance and connect to the CHDK device.

        :param device_info:   Information about device to connect to
        :type device_info:    :class:`DeviceInfo`
        """
        self.info = device_info
        self._lua = LuaContext()
        self._lua.globals.devspec = self.info._asdict()
        self._lua.pexecute("""
        con = chdku.connection({bus = devspec.bus_num,
                                dev = devspec.device_num})
        con:connect()
        """)
        self._con = self._lua.globals.con

    @property
    def is_connected(self):
        return self._lua.call("con:is_connected")

    @property
    def mode(self):
        """ The current mode of the device, one of `record` or `play`. """
        is_record, is_video, _ = self.lua_execute('return get_mode()')
        return 'record' if is_record else 'play'

    def switch_mode(self, mode):
        """ Change the mode of the device, must be one of `record` or `play`.
        """
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

    def _parse_message(self, raw_msg):
        value = raw_msg.value
        if raw_msg.subtype == 'table':
            value = parse_table(self._lua.eval(raw_msg.value))
        return Message(type=raw_msg.type, script_id=raw_msg.script_id,
                       value=value)

    def get_messages(self):
        """ Get all messages from device buffer

        :return:    Messages
        :rtype:     generator, yields :class:`Message`
        """
        while True:
            raw_msg = self._con.read_msg(self._con)
            if raw_msg.type == 'none':
                raise StopIteration()
            yield self._parse_message(raw_msg)

    def send_message(self, message, script_id=None):
        """ Send a message to the device

        :param message:     Message to be sent
        :type message:      str/unicode
        :param script_id:   ID of script that the message should be sent to,
                            defaults to the most recently started script
        :type script_id:    int/None
        """
        if script_id:
            self._lua.call("con:write_msg", message, script_id)
        else:
            self._lua.call("con:write_msg", message)

    def lua_execute(self, lua_code, wait=True, do_return=True, remote_libs=[]):
        """ Execute Lua code on the device.

        :param lua_code:    Lua code to execute
        :type lua_code:     str/unicode
        :param wait:        Block until code has finished executing
        :type wait:         bool
        :param do_return:   Return value of lua code, only if `wait=True`
        :type do_return:    bool
        :param remote_libs: Additional code modules from `rlibs.lua` (see
                            chdkptp source) that should be uploaded along with
                            the specified code
        :type remote_libs:  List of str/unicode with names of modules from
                            `rlibs.lua`

        :rtype:             bool/int/unicode/dict/tuple
        """
        # TODO: This should all really work with LuaContext.call, but for some
        # reason it fucks up the return values .-/
        remote_libs = "{%s}" % ", ".join("'%s'" % lib for lib in remote_libs)
        if not wait:
            self._lua.pexecute("con:exec([[%s]], {libs=%s})"
                               % (lua_code, remote_libs))
            return None
        if do_return and "return" not in lua_code:
            if ";" not in lua_code[:-1] and "\n" not in lua_code:
                lua_code = "return " + lua_code
            else:
                raise ValueError(
                    "`do_return` was specified, but no return statement was"
                    " specified in the supplied `lua_code`. Please change your"
                    " script so that it returns the value you want.")
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
            return_values.append(self._parse_message(rv).value)
        if len(return_values) == 1:
            return return_values[0]
        else:
            return tuple(return_values)

    def kill_scripts(self, flush=True):
        """ Terminate any running script on the device.

        :param flush:   Discard script messages
        :type flush:    bool
        """
        self._lua.call("con:exec", "", flush_cam_msgs=flush,
                       flush_host_msgs=flush, clobber=True)
        self._lua.call("con:wait_status", run=False)

    def upload_file(self, local_path, remote_path='A/', skip_checks=False):
        """ Upload a file to the device.

        :param local_paths:     Path to a local file
        :type local_paths:      str/unicode
        :param remote_path:     Target path on the device
        :type remote_path:      str/unicode
        :param skip_checks:     Skip sanity checks on the device, required if
                                a script is running on the device while
                                uploading.
        """
        # TODO: Test!
        local_path = os.path.abspath(local_path)
        remote_path = util.to_camerapath(remote_path)
        if os.path.isdir(local_path):
            raise ValueError("`local_path` must be a file, not a directory.")
        if not skip_checks:
            if remote_path.endswith("/"):
                try:
                    status = parse_table(
                        self._lua.call("con:stat", remote_path))
                except LuaError:
                    status = {'is_dir': False}
                if not status['is_dir']:
                    raise ValueError("Remote path '{0}' is not a directory. "
                                     "Please leave out the trailing slash if "
                                     "you are refering to a file")
                remote_path = os.path.join(remote_path,
                                           os.path.basename(local_path))
        self._lua.call("con:upload", local_path, remote_path)

    def batch_upload(self, local_paths, remote_path='A/'):
        """ Upload multiple files/directories to the device.

        :param local_paths:     Multiple locals paths
        :type local_paths:      collection of str/unicode
        :param remote_path:     Target path on the device
        :type remote_path:      str/unicode
        """
        remote_path = util.to_camerapath(remote_path)
        local_paths = [os.path.abspath(p) for p in local_paths]
        self._lua.call("con:mupload", self._lua.table(*local_paths),
                       remote_path, dirs=True, mtime=True, maxdepth=100)

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
        remote_path = util.to_camerapath(remote_path)
        path = local_path or tempfile.mkstemp()[1]
        self._lua.call("con:download", remote_path, path)
        if not local_path:
            with open(path, 'rb') as fp:
                rval = fp.read()
            os.unlink(path)
            return rval

    def batch_download(self, remote_paths, local_path='./', overwrite=False):
        """ Download multiple files/directories from the device.

        :param remote_paths:    Multiple paths on the device. The leading
                                'A/' is optional, it will be automatically
                                prepended if not specified
        :type remote_paths:     collection of str/unicode
        :param local_path:      Target path on the local file system
        :type local_path:       str/unicode
        :param overwrite:       Overwrite existing files
        :type overwrite:        bool
        """
        remote_paths = [util.to_camerapath(p) for p in remote_paths]
        local_path = os.path.abspath(local_path)
        self._lua.call("con:mdownload", self._lua.table(*remote_paths),
                       local_path, maxdepth=100, batchsize=20, dbgmem=False,
                       overwrite=overwrite)

    def delete_files(self, *remote_paths):
        """ Delete one or more files/directories from the device.

        :param remote_paths:    One or more paths on the device. The leading
                                'A/' is optional, it will be automatically
                                prepended if not specified
        """
        self._con.mdelete(self._con, self._lua.table(*remote_paths),
                          self._lua.table(skip_topdirs=True))

    def list_files(self, remote_path='A/DCIM', detailed=False):
        """ Get directory listing for a path on the device.

        :param remote_path: Path on the device
        :type remote_path:  str/unicode
        :param detailed:    Return detailed information about each file/dir
        :type detailed:     bool
        :return:            All files and directories in the path
        """
        remote_path = util.to_camerapath(remote_path)
        flist = self._lua.call("con:listdir", remote_path, dirsonly=False,
                               stat="*" if detailed else "/")
        if not detailed:
            return [os.path.join(remote_path, p) for p in flist.values()]
        else:
            return [tuple(os.path.join(remote_path,
                                       dict(info.items())['name']),
                          {k: v for k, v in info.items() if k != 'name'})
                    for info in flist.values()]

    def mkdir(self, remote_path):
        """ Create a directory on the device.
        Intermediate directories will be created as needed.

        :param remote_path: Path on the device
        :type remote_path:  str/unicode
        """
        remote_path = util.to_camerapath(remote_path)
        self._lua.call("con:mkdir_m", remote_path)

    def reconnect(self, wait=2000):
        """ Reset the connection to the device.

        :param wait:        Time in miliseconds to wait before attempting
                            to reconnect
        :type wait:         int
        """
        self._lua.call("con:reconnect", wait=wait, strict=True)

    def reboot(self, wait=3500, bootfile=None):
        """ Reboot the device.

        :param wait:        Time in miliseconds to wait before attempting
                            to reconnect
        :type wait:         int
        :param bootfile:    Optional file to boot. Must be the path to an
                            existing file on the device that is either an
                            unencoded binary or (for DryOS) an encoded .FI2
        :type bootfile:     str/unicode
        """
        if bootfile:
            bootfile = util.to_camerapath(bootfile)
        self.lua_execute("sleep(1000); reboot('{0}')".format(bootfile),
                         clobber=True)
        self.reconnect(wait)

    def get_frames(self, format='ppm', scaled=None):
        """ Get a generator that yields frames from the device's viewport.

        :param format:      Target format for frames, if `None` the raw image
                            data is returned
        :type format:       One of 'ppm', 'jpg', 'png'
        :param scaled:      The raw image has the wrong aspect ratio, with
                            this flag this can be corrected on the device,
                            which results in some quality degradation, but
                            is very fast.
                            Defaults to `True` when format is 'ppm', otherwise
                            `False`.
        :type scaled:       bool
        :return:            Generator that yields bytestrings with frame data
                            in the specified format
        """
        if format not in ('ppm', 'jpg', 'png'):
            raise ValueError("`format` has to be one of 'ppm', 'jpg' or 'png'")
        if scaled is None:
            scaled = (format == 'ppm')
        while True:
            imgdata = self._lua.eval("""
                function(skip)
                    local frame = con:get_live_data(nil, 1)
                    local pimg = liveimg.get_viewport_pimg(nil, frame, skip)
                    local lb = pimg:to_lbuf_packed_rgb(nil)
                    local header = string.format('P6\\n%d\\n%d\\n%d\\n',
                                                pimg:width(), pimg:height(),
                                                255)
                    return header .. lb:string()
                end
            """)(scaled)
            if format == 'ppm':
                yield imgdata
            else:
                try:
                    from PIL import Image
                except ImportError:
                    raise RuntimeError(
                        "To convert into JPEG or PNG, please install the "
                        "`pillow` package.")
                img = Image.open(StringIO.StringIO(imgdata))
                width, height = img.size
                img.resize((width/2, height))
                imgdata = img.tobytes('PNG' if format == 'png' else 'JPEG')
                yield imgdata

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
        :param dng:             Dump raw framebuffer in DNG format
                                (default: False)
        :type dng:              boolean
        :param wait:            Wait for capture to complete (default: True)
        :type wait:             boolean
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

        if not kwargs.get('stream', True):
            return self._shoot_nonstreaming(
                options, wait=kwargs.get('wait', True),
                download=kwargs.get('download_after', False),
                remove=kwargs.get('remove_after', False))
        else:
            return self._shoot_streaming(options, dng=kwargs.get('dng', False))

    def _shoot_nonstreaming(self, options, wait=True, download=False,
                            remove=False):
        if not wait:
            self.lua_execute("rlib_shoot(%s)" % options, wait=False,
                             remote_libs=['rlib_shoot'])
            return
        status = self.lua_execute(
            "return rlib_shoot(%s)" % options,
            remote_libs=['serialize_msgs', 'rlib_shoot'])
        # TODO: Check for errors
        img_path = "{0}/IMG_{1:04}.JPG".format(status['dir'], status['exp'])
        rval = None
        if download:
            rval = self.download_file(img_path)
        if remove:
            self.delete_files(img_path)
        return rval

    def _shoot_streaming(self, options, dng=False):
        self.lua_execute(
            "return rs_init(%s)" % options, remote_libs=['rs_shoot_init'])
        # TODO: Check for errors
        self.lua_execute("rs_shoot(%s)" % options,
                         remote_libs=['rs_shoot'], wait=False)
        rcopts = {}
        img_data = self._lua.table()
        if dng:
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
        self._con.capture_get_data_pcall(
            self._con, self._lua.table(**rcopts))
        self._con.wait_status_pcall(
            self._con, self._lua.table(run=False, timeout=30000))
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
        dng_download = (not kwargs.get('stream', True)
                        and kwargs.get('dng', False)
                        and (kwargs.get('download_after', False)
                             or kwargs.get('remove_after', False)))
        if dng_download:
            raise NotImplementedError(
                "Non-streaming capture with subsequent download/removal is "
                "only supported for JPEG at the moment.")

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
        else:
            options['info'] = True
        return options
