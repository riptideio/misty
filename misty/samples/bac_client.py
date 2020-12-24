#!/usr/bin/env python

"""
This application presents a 'console' prompt to the user asking for Who-Is and I-Am
commands which create the related APDUs, then lines up the coorresponding I-Am
for incoming traffic and prints out the contents.
"""

from __future__ import absolute_import
from __future__ import print_function
import sys
import os

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser
from bacpypes.consolecmd import ConsoleCmd

from bacpypes.core import deferred
from bacpypes.core import run, enable_sleeping
from bacpypes.iocb import IOCB

from bacpypes.pdu import Address, GlobalBroadcast
from bacpypes.apdu import SimpleAckPDU
from bacpypes.apdu import ReadPropertyRequest, ReadPropertyACK, WritePropertyRequest
from bacpypes.primitivedata import Unsigned, ObjectIdentifier
from bacpypes.object import get_datatype
from bacpypes.constructeddata import Array
from bacpypes.apdu import WhoIsRequest, IAmRequest
from bacpypes.errors import DecodingError

from bacpypes.primitivedata import Null, Atomic, Boolean, Integer, \
    Real, Double, OctetString, CharacterString, BitString, Date, Time
from bacpypes.constructeddata import Any, AnyAtomic

from misty.mstplib import MSTPSimpleApplication
from bacpypes.local.device import LocalDeviceObject
from six.moves import range

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# globals
this_device = None
this_application = None

#
#   WhoIsIAmApplication
#

@bacpypes_debugging
class WhoIsIAmApplication(MSTPSimpleApplication):

    def __init__(self, *args):
        if _debug: WhoIsIAmApplication._debug("__init__ %r", args)
        MSTPSimpleApplication.__init__(self, *args)

        # keep track of requests to line up responses
        self._request = None

    def request(self, apdu):
        if _debug: WhoIsIAmApplication._debug("request %r", apdu)

        # save a copy of the request
        self._request = apdu

        # forward it along
        MSTPSimpleApplication.request(self, apdu)

    def confirmation(self, apdu):
        if _debug: WhoIsIAmApplication._debug("confirmation %r", apdu)

        # forward it along
        MSTPSimpleApplication.confirmation(self, apdu)

    def indication(self, apdu):
        if _debug: WhoIsIAmApplication._debug("indication %r", apdu)

        if (isinstance(apdu, IAmRequest)):
            device_type, device_instance = apdu.iAmDeviceIdentifier
            if device_type != 'device':
                raise DecodingError("invalid object type")

            # print out the contents
            sys.stdout.write('pduSource = ' + repr(apdu.pduSource) + '\n')
            sys.stdout.write('iAmDeviceIdentifier = ' + str(apdu.iAmDeviceIdentifier) + '\n')
            sys.stdout.write('maxAPDULengthAccepted = ' + str(apdu.maxAPDULengthAccepted) + '\n')
            sys.stdout.write('segmentationSupported = ' + str(apdu.segmentationSupported) + '\n')
            sys.stdout.write('vendorID = ' + str(apdu.vendorID) + '\n')
            sys.stdout.flush()

        # forward it along
        MSTPSimpleApplication.indication(self, apdu)

#
#   BacnetClientConsoleCmd
#

@bacpypes_debugging
class BacnetClientConsoleCmd(ConsoleCmd):

    def do_whois(self, args):
        """whois [ <addr>] [ <lolimit> <hilimit> ]"""
        args = args.split()
        if _debug: BacnetClientConsoleCmd._debug("do_whois %r", args)

        try:
            # build a request
            request = WhoIsRequest()
            if (len(args) == 1) or (len(args) == 3):
                request.pduDestination = Address(args[0])
                del args[0]
            else:
                request.pduDestination = GlobalBroadcast()

            if len(args) == 2:
                request.deviceInstanceRangeLowLimit = int(args[0])
                request.deviceInstanceRangeHighLimit = int(args[1])
            if _debug: BacnetClientConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: BacnetClientConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            this_application.request_io(iocb)

        except Exception as err:
            BacnetClientConsoleCmd._exception("exception: %r", err)

    def do_write(self, args):
        """write <addr> <type>:<inst> <prop> <value> [ <indx> ] [ <priority> ]"""
        args = args.split()
        BacnetClientConsoleCmd._debug("do_write %r", args)

        try:
            addr, obj_id, prop_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value
            value = args[3]

            indx = None
            if len(args) >= 5:
                if args[4] != "-":
                    indx = int(args[4])
            if _debug: BacnetClientConsoleCmd._debug("    - indx: %r", indx)

            priority = None
            if len(args) >= 6:
                priority = int(args[5])
            if _debug: BacnetClientConsoleCmd._debug("    - priority: %r", priority)

            # get the datatype
            datatype = get_datatype(obj_id[0], prop_id)
            if _debug: BacnetClientConsoleCmd._debug("    - datatype: %r", datatype)

            # change atomic values into something encodeable, null is a special case
            if (value == 'null'):
                value = Null()
            elif issubclass(datatype, AnyAtomic):
                dtype, dvalue = value.split(':', 1)
                if _debug: BacnetClientConsoleCmd._debug("    - dtype, dvalue: %r, %r", dtype, dvalue)

                datatype = {
                    'b': Boolean,
                    'u': lambda x: Unsigned(int(x)),
                    'i': lambda x: Integer(int(x)),
                    'r': lambda x: Real(float(x)),
                    'd': lambda x: Double(float(x)),
                    'o': OctetString,
                    'c': CharacterString,
                    'bs': BitString,
                    'date': Date,
                    'time': Time,
                    'id': ObjectIdentifier,
                    }[dtype]
                if _debug: BacnetClientConsoleCmd._debug("    - datatype: %r", datatype)

                value = datatype(dvalue)
                if _debug: BacnetClientConsoleCmd._debug("    - value: %r", value)

            elif issubclass(datatype, Atomic):
                if datatype is Integer:
                    value = int(value)
                elif datatype is Real:
                    value = float(value)
                elif datatype is Unsigned:
                    value = int(value)
                value = datatype(value)
            elif issubclass(datatype, Array) and (indx is not None):
                if indx == 0:
                    value = Integer(value)
                elif issubclass(datatype.subtype, Atomic):
                    value = datatype.subtype(value)
                elif not isinstance(value, datatype.subtype):
                    raise TypeError("invalid result datatype, expecting %s" % (datatype.subtype.__name__,))
            elif not isinstance(value, datatype):
                raise TypeError("invalid result datatype, expecting %s" % (datatype.__name__,))
            if _debug: BacnetClientConsoleCmd._debug("    - encodeable value: %r %s", value, type(value))

            # build a request
            request = WritePropertyRequest(
                objectIdentifier=obj_id,
                propertyIdentifier=prop_id
                )
            request.pduDestination = Address(addr)

            # save the value
            request.propertyValue = Any()
            try:
                request.propertyValue.cast_in(value)
            except Exception as error:
                BacnetClientConsoleCmd._exception("WriteProperty cast error: %r", error)

            # optional array index
            if indx is not None:
                request.propertyArrayIndex = indx

            # optional priority
            if priority is not None:
                request.priority = priority

            if _debug: BacnetClientConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: BacnetClientConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            this_application.request_io(iocb)

            # wait for it to complete
            iocb.wait()

            # do something for success
            if iocb.ioResponse:
                # should be an ack
                if not isinstance(iocb.ioResponse, SimpleAckPDU):
                    if _debug: BacnetClientConsoleCmd._debug("    - not an ack")
                    return

                sys.stdout.write("ack\n")

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + '\n')

        except Exception as error:
            BacnetClientConsoleCmd._exception("exception: %r", error)

    def do_iam(self, args):
        """iam"""
        args = args.split()
        if _debug: BacnetClientConsoleCmd._debug("do_iam %r", args)

        try:
            # build a request
            request = IAmRequest()
            request.pduDestination = GlobalBroadcast()

            # set the parameters from the device object
            request.iAmDeviceIdentifier = this_device.objectIdentifier
            request.maxAPDULengthAccepted = this_device.maxApduLengthAccepted
            request.segmentationSupported = this_device.segmentationSupported
            request.vendorID = this_device.vendorIdentifier
            if _debug: BacnetClientConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: BacnetClientConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            this_application.request_io(iocb)

        except Exception as err:
            BacnetClientConsoleCmd._exception("exception: %r", err)

    def do_read(self, args):
        """read <addr> <type>:<inst> <prop> [ <indx> ]"""
        args = args.split()
        if _debug: BacnetClientConsoleCmd._debug("do_read %r", args)

        try:
            addr, obj_id, prop_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value

            datatype = get_datatype(obj_id[0], prop_id)
            if not datatype:
                raise ValueError("invalid property for object type")

            # build a request
            request = ReadPropertyRequest(
                objectIdentifier=obj_id,
                propertyIdentifier=prop_id,
                )
            request.pduDestination = Address(addr)

            if len(args) == 4:
                request.propertyArrayIndex = int(args[3])
            if _debug: BacnetClientConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: BacnetClientConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            this_application.request_io(iocb)

            # wait for it to complete
            iocb.wait()

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + '\n')

            # do something for success
            elif iocb.ioResponse:
                apdu = iocb.ioResponse

                # should be an ack
                if not isinstance(apdu, ReadPropertyACK):
                    if _debug: BacnetClientConsoleCmd._debug("    - not an ack")
                    return

                # find the datatype
                datatype = get_datatype(apdu.objectIdentifier[0], apdu.propertyIdentifier)
                if _debug: BacnetClientConsoleCmd._debug("    - datatype: %r", datatype)
                if not datatype:
                    raise TypeError("unknown datatype")

                # special case for array parts, others are managed by cast_out
                if issubclass(datatype, Array) and (apdu.propertyArrayIndex is not None):
                    if apdu.propertyArrayIndex == 0:
                        value = apdu.propertyValue.cast_out(Unsigned)
                    else:
                        value = apdu.propertyValue.cast_out(datatype.subtype)
                else:
                    value = apdu.propertyValue.cast_out(datatype)
                if _debug: BacnetClientConsoleCmd._debug("    - value: %r", value)

                sys.stdout.write(str(value) + '\n')
                if hasattr(value, 'debug_contents'):
                    value.debug_contents(file=sys.stdout)
                sys.stdout.flush()

            # do something with nothing?
            else:
                if _debug: BacnetClientConsoleCmd._debug("    - ioError or ioResponse expected")

        except Exception as error:
            BacnetClientConsoleCmd._exception("exception: %r", error)

    def do_mstpstat(self, args):
        """discover <addr> <device-id>"""
        args = args.split()
        mstp_lib=this_application.mux.directPort.mstp_lib
        mstp_lib.get_mstpstats()

    def _is_writable(self, fname):
        try:
            abs_fname = os.path.abspath(fname)
            with open(abs_fname, "w") as fp:
                return True
        except Exception:
            pass
        return False

    def do_mstpdbg(self, args):
        """mstpdbg <enable|disable|status> [filename]"""

        if len(args) == 0:
            print("mstpdbg <enable|disable|status> <filename>")
            return

        args = args.split()
        dbg_type = args[0]
        if dbg_type not in ("enable", "disable", "status"):
            print("mstpdbg <enable|disable|status> <filename>")
            return
        if dbg_type == 'enable':
            if len(args) != 2:
                print("mstpdbg enable <filename>")
                return
            # check if the filename is writable
            fname = args[1]
            if not self._is_writable(fname):
                print("'{}' is not writable".format(os.path.abspath(fname)))
                return

            fname = os.path.abspath(fname)

            # enable debug
            mstp_lib=this_application.mux.directPort.mstp_lib
            mstp_lib.enable_debug_flag(fname)
        elif dbg_type == 'disable':
            mstp_lib=this_application.mux.directPort.mstp_lib
            mstp_lib.disable_debug_flag()
        elif dbg_type == 'status':
            mstp_lib=this_application.mux.directPort.mstp_lib
            mstp_lib.status_debug_flag()
        else:
            print("mstpdbg <enable|disable|status> <filename>")

    def do_discover(self, args):
        """discover <addr> <device-id>"""
        args = args.split()
        try:

            if len(args) != 2:
                raise ValueError('Expected 2 arguments')

            addr, device_id = args[:2]

            addr = int(addr)
            device_id = int(device_id)

            # used across requests
            self._instance_list = [0]
            self._first_req = True
            self._addr = addr
            self._device_id = device_id

            self._discovery()

        except Exception as error:
            BacnetClientConsoleCmd._exception("exception: %r", error)

    def _discovery(self):
        global device_address

        # build a request
        obj_type, prop_id = ('device', 'objectList')

        # build a request
        request = ReadPropertyRequest(
            objectIdentifier=(obj_type, self._device_id),
            propertyIdentifier=prop_id,
        )
        request.pduSource = Address(this_device._address)
        request.pduDestination = Address(int(self._addr))
        request.propertyArrayIndex = self._instance_list.pop(0)

        if _debug:
            BacnetClientConsoleCmd._debug("    - request: %r", request)

        # make an IOCB
        iocb = IOCB(request)

        # set a callback for the response
        iocb.add_callback(self._discovery_response)
        if _debug:
            BacnetClientConsoleCmd._debug("    - iocb: %r", iocb)

        # send the request
        this_application.request_io(iocb)

    def _discovery_response(self, iocb):
        if _debug:
            BacnetClientConsoleCmd._debug("complete_request %r", iocb)

        if iocb.ioResponse:
            apdu = iocb.ioResponse

            # should be an ack
            if not isinstance(apdu, ReadPropertyACK):
                if _debug:
                    BacnetClientConsoleCmd._debug("    - not an ack")
                return

            # find the datatype
            datatype = get_datatype(
                apdu.objectIdentifier[0], apdu.propertyIdentifier
            )
            if _debug:
                BacnetClientConsoleCmd._debug("    - datatype: %r", datatype)
            if not datatype:
                raise TypeError("unknown datatype")

            # special case for array parts, others are managed by cast_out
            if (
                (issubclass(datatype, Array)) and
                (apdu.propertyArrayIndex is not None)
            ):
                if apdu.propertyArrayIndex == 0:
                    value = apdu.propertyValue.cast_out(Unsigned)
                else:
                    value = apdu.propertyValue.cast_out(datatype.subtype)
            else:
                value = apdu.propertyValue.cast_out(datatype)
            if _debug:
                BacnetClientConsoleCmd._debug("    - value: %r", value)

            sys.stdout.write(str(value) + '\n')

            if hasattr(value, 'debug_contents'):
                value.debug_contents(file=sys.stdout)
            sys.stdout.flush()

            if self._first_req:
                self._instance_list = list(range(1, value+1))
                self._first_req = False

                # fire off another request
                deferred(self._discovery)
                return

            if self._instance_list:
                # fire off another request
                deferred(self._discovery)

    def do_rtn(self, args):
        """rtn <addr> <net> ... """
        args = args.split()
        if _debug: BacnetClientConsoleCmd._debug("do_rtn %r", args)

        # provide the address and a list of network numbers
        router_address = Address(args[0])
        network_list = [int(arg) for arg in args[1:]]

        # pass along to the service access point
        this_application.nsap.add_router_references(None, router_address, network_list)


#
#   main
#

def main():
    global this_device, this_application

    # parse the command line arguments
    args = ConfigArgumentParser(description=__doc__).parse_args()

    if _debug: _log.debug("initialization")
    if _debug: _log.debug("    - args: %r", args)

    # make a device object
    mstp_args = {
        '_address': int(args.ini.address),
        '_interface':str(args.ini.interface),
        '_max_masters': int(args.ini.max_masters),
        '_baudrate': int(args.ini.baudrate),
        '_maxinfo': int(args.ini.maxinfo),
    }

    if hasattr(args.ini, 'mstpdbgfile'):
        mstp_args['_mstpdbgfile'] = str(args.ini.mstpdbgfile)

    this_device = LocalDeviceObject(ini=args.ini, **mstp_args)
    if _debug: _log.debug("    - this_device: %r", this_device)

    # make a simple application
    this_application = WhoIsIAmApplication(
        this_device, args.ini.address,
        )
    if _debug: _log.debug("    - this_application: %r", this_application)

    # make a console
    this_console = BacnetClientConsoleCmd()
    if _debug: _log.debug("    - this_console: %r", this_console)

    # enable sleeping will help with threads
    enable_sleeping()

    _log.debug("running")

    run()

    _log.debug("fini")


if __name__ == "__main__":
    main()
