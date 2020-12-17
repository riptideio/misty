#!/usr/bin/env python

"""
This application presents a 'console' prompt to the user asking for commands.

For 'read' commands it will create ReadPropertyRequest PDUs, then lines up the
coorresponding ReadPropertyACK and prints the value.  For 'write' commands it
will create WritePropertyRequst PDUs and prints out a simple acknowledgement.
"""

from __future__ import absolute_import
import sys

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser
from bacpypes.consolecmd import ConsoleCmd

from bacpypes.core import run, deferred, enable_sleeping
from bacpypes.iocb import IOCB

from bacpypes.pdu import Address
from bacpypes.object import get_datatype

from bacpypes.apdu import SimpleAckPDU, \
    ReadPropertyRequest, ReadPropertyACK, WritePropertyRequest
from bacpypes.primitivedata import Null, Atomic, Boolean, Unsigned, Integer, \
    Real, Double, OctetString, CharacterString, BitString, Date, Time, ObjectIdentifier
from bacpypes.constructeddata import Array, Any, AnyAtomic

from misty.mstplib import MSTPSimpleApplication
from bacpypes.local.device import LocalDeviceObject

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# globals
this_application = None

#
#   ReadWritePropertyConsoleCmd
#

@bacpypes_debugging
class ReadWritePropertyConsoleCmd(ConsoleCmd):

    def do_read(self, args):
        """read <addr> <objid> <prop> [ <indx> ]"""
        args = args.split()
        if _debug: ReadWritePropertyConsoleCmd._debug("do_read %r", args)

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
            if _debug: ReadWritePropertyConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: ReadWritePropertyConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            deferred(this_application.request_io, iocb)

            # wait for it to complete
            iocb.wait()

            # do something for success
            if iocb.ioResponse:
                apdu = iocb.ioResponse

                # should be an ack
                if not isinstance(apdu, ReadPropertyACK):
                    if _debug: ReadWritePropertyConsoleCmd._debug("    - not an ack")
                    return

                # find the datatype
                datatype = get_datatype(apdu.objectIdentifier[0], apdu.propertyIdentifier)
                if _debug: ReadWritePropertyConsoleCmd._debug("    - datatype: %r", datatype)
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
                if _debug: ReadWritePropertyConsoleCmd._debug("    - value: %r", value)

                sys.stdout.write(str(value) + '\n')
                if hasattr(value, 'debug_contents'):
                    value.debug_contents(file=sys.stdout)
                sys.stdout.flush()

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + '\n')

        except Exception as error:
            ReadWritePropertyConsoleCmd._exception("exception: %r", error)

    def do_write(self, args):
        """write <addr> <type> <inst> <prop> <value> [ <indx> ] [ <priority> ]"""
        args = args.split()
        ReadWritePropertyConsoleCmd._debug("do_write %r", args)

        try:
            addr, obj_id, prop_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value
            value = args[3]

            indx = None
            if len(args) >= 5:
                if args[4] != "-":
                    indx = int(args[4])
            if _debug: ReadWritePropertyConsoleCmd._debug("    - indx: %r", indx)

            priority = None
            if len(args) >= 6:
                priority = int(args[5])
            if _debug: ReadWritePropertyConsoleCmd._debug("    - priority: %r", priority)

            # get the datatype
            datatype = get_datatype(obj_id[0], prop_id)
            if _debug: ReadWritePropertyConsoleCmd._debug("    - datatype: %r", datatype)

            # change atomic values into something encodeable, null is a special case
            if (value == 'null'):
                value = Null()
            elif issubclass(datatype, AnyAtomic):
                dtype, dvalue = value.split(':', 1)
                if _debug: ReadWritePropertyConsoleCmd._debug("    - dtype, dvalue: %r, %r", dtype, dvalue)

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
                if _debug: ReadWritePropertyConsoleCmd._debug("    - datatype: %r", datatype)

                value = datatype(dvalue)
                if _debug: ReadWritePropertyConsoleCmd._debug("    - value: %r", value)

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
            if _debug: ReadWritePropertyConsoleCmd._debug("    - encodeable value: %r %s", value, type(value))

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
                ReadWritePropertyConsoleCmd._exception("WriteProperty cast error: %r", error)

            # optional array index
            if indx is not None:
                request.propertyArrayIndex = indx

            # optional priority
            if priority is not None:
                request.priority = priority

            if _debug: ReadWritePropertyConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: ReadWritePropertyConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            deferred(this_application.request_io, iocb)

            # wait for it to complete
            iocb.wait()

            # do something for success
            if iocb.ioResponse:
                # should be an ack
                if not isinstance(iocb.ioResponse, SimpleAckPDU):
                    if _debug: ReadWritePropertyConsoleCmd._debug("    - not an ack")
                    return

                sys.stdout.write("ack\n")

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + '\n')

        except Exception as error:
            ReadWritePropertyConsoleCmd._exception("exception: %r", error)

    def do_rtn(self, args):
        """rtn <addr> <net> ... """
        args = args.split()
        if _debug: ReadWritePropertyConsoleCmd._debug("do_rtn %r", args)

        # provide the address and a list of network numbers
        router_address = Address(args[0])
        network_list = [int(arg) for arg in args[1:]]

        # pass along to the service access point
        this_application.nsap.update_router_references(None, router_address, network_list)


#
#   __main__
#

def main():
    global this_application

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
    # make a device object
    this_device = LocalDeviceObject(ini=args.ini, **mstp_args)
    if _debug: _log.debug("    - this_device: %r", this_device)

    # make a simple application
    this_application = MSTPSimpleApplication(this_device, args.ini.address)

    # make a console
    this_console = ReadWritePropertyConsoleCmd()
    if _debug: _log.debug("    - this_console: %r", this_console)

    # enable sleeping will help with threads
    enable_sleeping()

    _log.debug("running")

    run()

    _log.debug("fini")

if __name__ == "__main__":
    main()
