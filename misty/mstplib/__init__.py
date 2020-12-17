"""
Copyright (c) 2018 by Riptide I/O
All rights reserved.
"""

from __future__ import absolute_import
from __future__ import print_function
import asyncore
import socket
import six.moves.queue as queue
import warnings
import binascii
import os
import time
import struct
import atexit
import glob
import tempfile
import six
from ctypes import cdll


from bacpypes.pdu import Address, PCI, PDUData
from bacpypes.debugging import bacpypes_debugging, DebugContents, ModuleLogger
from bacpypes.comm import ApplicationServiceElement, bind, PDU
from bacpypes.iocb import IOController, SieveQueue
from bacpypes.app import ApplicationIOController
from bacpypes.core import deferred

from bacpypes.pdu import Address
from bacpypes.udp import UDPActor


from bacpypes.primitivedata import ObjectIdentifier

from bacpypes.capability import Collector
from bacpypes.appservice import StateMachineAccessPoint, ApplicationServiceAccessPoint
from bacpypes.netservice import NetworkServiceAccessPoint, NetworkServiceElement
from bacpypes.bvllservice import BIPSimple, BIPForeign, AnnexJCodec, UDPMultiplexer, _MultiplexServer, _MultiplexClient, OriginalUnicastNPDU, OriginalBroadcastNPDU

from bacpypes.bvll import BVLPDU, DeleteForeignDeviceTableEntry, \
    DistributeBroadcastToNetwork, FDTEntry, ForwardedNPDU, \
    OriginalBroadcastNPDU, OriginalUnicastNPDU, \
    ReadBroadcastDistributionTable, ReadBroadcastDistributionTableAck, \
    ReadForeignDeviceTable, ReadForeignDeviceTableAck, RegisterForeignDevice, \
    Result, WriteBroadcastDistributionTable, bvl_pdu_types


from bacpypes.apdu import UnconfirmedRequestPDU, ConfirmedRequestPDU, \
    SimpleAckPDU, ComplexAckPDU, ErrorPDU, RejectPDU, AbortPDU, Error

from bacpypes.errors import ExecutionError, UnrecognizedService, AbortException, RejectException

# for computing protocol services supported
from bacpypes.apdu import confirmed_request_types, unconfirmed_request_types, \
    ConfirmedServiceChoice, UnconfirmedServiceChoice
from bacpypes.basetypes import ServicesSupported

# basic services
from bacpypes.service.device import WhoIsIAmServices
from bacpypes.service.object import ReadWritePropertyServices
from bacpypes.comm import Client, Server, bind, \
    ServiceAccessPoint, ApplicationServiceElement


# some debugging
_debug = 0
_log = ModuleLogger(globals())

#
#   MSTPSAP
#

@bacpypes_debugging
class MSTPSAP(ServiceAccessPoint):

    def __init__(self, sap=None):
        """A MSTP service access point."""
        if _debug: MSTPSAP._debug("__init__ sap=%r", sap)
        ServiceAccessPoint.__init__(self, sap)

    def sap_indication(self, pdu):
        if _debug: MSTPSAP._debug("sap_indication %r", pdu)

        # this is a request initiated by the ASE, send this downstream
        self.request(pdu)

    def sap_confirmation(self, pdu):
        if _debug: MSTPSAP._debug("sap_confirmation %r", pdu)

        # this is a response from the ASE, send this downstream
        self.request(pdu)

#
#   MSTPSimple
#

@bacpypes_debugging
class MSTPSimple(MSTPSAP, Client, Server):

    def __init__(self, sapID=None, cid=None, sid=None):
        """A MSTP node."""
        if _debug: MSTPSimple._debug("__init__ sapID=%r cid=%r sid=%r", sapID, cid, sid)
        MSTPSAP.__init__(self, sapID)
        Client.__init__(self, cid)
        Server.__init__(self, sid)

    def indication(self, pdu):
        if _debug: MSTPSimple._debug("indication %r", pdu)

        # check for local stations
        if pdu.pduDestination.addrType == Address.localStationAddr:
            # make an original unicast PDU
            xpdu = OriginalUnicastNPDU(pdu, destination=pdu.pduDestination, user_data=pdu.pduUserData)
            if _debug: MSTPSimple._debug("    - xpdu: %r", xpdu)

            # send it downstream
            self.request(xpdu)

        # check for broadcasts
        elif pdu.pduDestination.addrType == Address.localBroadcastAddr:
            # make an original broadcast PDU
            xpdu = OriginalBroadcastNPDU(pdu, destination=pdu.pduDestination, user_data=pdu.pduUserData)
            if _debug: MSTPSimple._debug("    - xpdu: %r", xpdu)

            # send it downstream
            self.request(xpdu)

        else:
            MSTPSimple._warning("invalid destination address: %r", pdu.pduDestination)

    def confirmation(self, pdu):
        if _debug: MSTPSimple._debug("confirmation %r", pdu)

        # send it upstream
        self.response(pdu)

#
#   MSTPDirector
#

@bacpypes_debugging
class MSTPDirector(asyncore.dispatcher, Server, ServiceAccessPoint):
    mstp_dir = None
    mstp_lib = None

    def __init__(
        self, localDevice, address, timeout=0, reuse=False, actorClass=UDPActor,
        sid=None, sapID=None
    ):
        if _debug:
            MSTPDirector._debug(
                "__init__ %r timeout=%r reuse=%r actorClass=%r sid=%r sapID=%r",
                address, timeout, reuse, actorClass, sid, sapID
            )
        Server.__init__(self, sid)
        ServiceAccessPoint.__init__(self, sapID)

        # check the actor class
        if not issubclass(actorClass, UDPActor):
            raise TypeError("actorClass must be a subclass of UDPActor")
        self.actorClass = actorClass

        # save the timeout for actors
        self.timeout = timeout

        # save the localDevice
        self.localDevice = localDevice

        # save the address
        self.address = address

        interface_filename = os.path.basename(self.localDevice._interface)
        interface_devname = self.localDevice._interface

        asyncore.dispatcher.__init__(self)

        # ask the dispatcher for a socket
        self.create_socket(socket.AF_UNIX, socket.SOCK_DGRAM)

        # if the reuse parameter is provided, set the socket option
        if reuse:
            self.set_reuse_addr()

        # proceed with the bind
        if hasattr(self.localDevice, '_mstp_dir'):
            mstp_dir = self.localDevice._mstp_dir
        else:
            mstp_dir = '/var/tmp'

        mstp_dir = tempfile.mkdtemp(prefix="ma_",dir=mstp_dir)
        MSTPDirector.mstp_dir = mstp_dir

        my_addr = '{}/mstp{}'.format(mstp_dir, interface_filename)
        try:
            os.remove(my_addr)
        except:
            pass

        # Call the library to init the mstp_agent
        dirname=os.path.dirname(__file__)
        libmstp_path=os.path.join(dirname, "libmstp_agent.so")
        mstp_lib = cdll.LoadLibrary(libmstp_path)
        MSTPDirector.mstp_lib = mstp_lib


        self.bind(my_addr)
        if _debug: MSTPDirector._debug("    - getsockname: %r", self.socket.getsockname())

        # allow it to send broadcasts
        self.socket.setsockopt( socket.SOL_SOCKET, socket.SO_BROADCAST, 1 )

        # create the request queue
        self.request = queue.Queue()

        # start with an empty peer pool
        self.peers = {}


        #send control stuff
        # 0x5 - Mac Address
        # 127 - Max Masters
        # 38400 - Baud rate
        # 0x1 - Max info Frames
        mac = str(self.address)
        mac = int(mac)
        max_masters = self.localDevice._max_masters
        baud_rate = self.localDevice._baudrate
        maxinfo = self.localDevice._maxinfo
        buf = struct.pack('iiii', mac, max_masters, baud_rate, maxinfo);

        if hasattr(self.localDevice, '_mstpdbgfile'):
            fname = self.localDevice._mstpdbgfile
            mstp_lib.enable_debug_flag(fname)

        if six.PY3:
            interface_devname_b = six.ensure_binary(interface_devname)
            mstp_dir_b=six.ensure_binary(mstp_dir)
            mstp_lib.init(buf, interface_devname_b, mstp_dir_b)
        else:
            mstp_lib.init(buf, interface_devname, mstp_dir)


        # to ensure that the server is ready
        time.sleep(0.5)

        # server to send the MSTP PDU's
        self.server_address = '{}/mstp_server'.format(mstp_dir)
        self.socket.connect(self.server_address)

    @staticmethod
    @atexit.register
    def atexit_handler():
        if MSTPDirector.mstp_dir is None:
            return

        files = glob.glob("{}/mstp*".format(MSTPDirector.mstp_dir))
        for f in files:
            os.remove(f)
        os.rmdir(MSTPDirector.mstp_dir)
        print("Cleaned up MSTP temp directory")

    def add_actor(self, actor):
        """Add an actor when a new one is connected."""
        if _debug: MSTPDirector._debug("add_actor %r", actor)

        self.peers[actor.peer] = actor

        # tell the ASE there is a new client
        if self.serviceElement:
            self.sap_request(add_actor=actor)

    def del_actor(self, actor):
        """Remove an actor when the socket is closed."""
        if _debug: MSTPDirector._debug("del_actor %r", actor)

        del self.peers[actor.peer]

        # tell the ASE the client has gone away
        if self.serviceElement:
            self.sap_request(del_actor=actor)

    def actor_error(self, actor, error):
        if _debug: MSTPDirector._debug("actor_error %r %r", actor, error)

        # tell the ASE the actor had an error
        if self.serviceElement:
            self.sap_request(actor_error=actor, error=error)

    def get_actor(self, address):
        return self.peers.get(address, None)

    def handle_connect(self):
        if _debug: MSTPDirector._debug("handle_connect")

    def readable(self):
        return 1

    def handle_read(self):
        if _debug: MSTPDirector._debug("handle_read")

        try:
            msg, addr = self.socket.recvfrom(512)
            if _debug: MSTPDirector._debug("    - received %d octets ", len(msg))
            pdu = PDU(msg,destination=int(str(self.address)))
            mstp_src = pdu.get()
            pdu.pduSource = Address(mstp_src)

            if _debug: MSTPDirector._debug("Received MSTP PDU={}".format(str(pdu)))

            # send the PDU up to the client
            deferred(self._response, pdu)

        except socket.timeout as err:
            if _debug: MSTPDirector._debug("    - socket timeout: %s", err)

        except socket.error as err:
            if err.args[0] == 11:
                pass
            else:
                if _debug: MSTPDirector._debug("    - socket error: %s", err)

                # pass along to a handler
                self.handle_error(err)

        except Exception as e:
            MSTPDirector._error('Exception in handle_read: {}'.format(e))

    def writable(self):
        """Return true iff there is a request pending."""
        return (not self.request.empty())

    def handle_write(self):
        """get a PDU from the queue and send it."""
        if _debug: MSTPDirector._debug("handle_write")

        try:
            pdu = self.request.get()
            pdu.pduSource=self.address

            if _debug: MSTPDirector._debug("Sending MSTP PDU={}".format(str(pdu)))

            # format is 0 for data, src_mac, payload
            if six.PY3:
                pdu.pduData.insert(0, int(str(pdu.pduDestination)))
            else:
                mstpData = chr(int(str(pdu.pduDestination))) + pdu.pduData
                pdu.pduData = mstpData


            sent = self.socket.send(pdu.pduData) # , pdu.pduDestination)
            if _debug: MSTPDirector._debug("    - sent %d octets to %s", sent, pdu.pduDestination)

        except socket.error as err:
            if _debug: MSTPDirector._debug("    - socket error: %s", err)

            # get the peer
            peer = self.peers.get(pdu.pduDestination, None)
            if peer:
                # let the actor handle the error
                peer.handle_error(err)
            else:
                # let the director handle the error
                self.handle_error(err)

    def close_socket(self):
        """Close the socket."""
        if _debug: MSTPDirector._debug("close_socket")
        self.socket.close()
        self.close()
        self.socket = None

    def handle_close(self):
        """Remove this from the monitor when it's closed."""
        if _debug: MSTPDirector._debug("handle_close")

        self.close()
        self.socket = None

    def handle_error(self, error=None):
        """Handle an error..."""
        if _debug: MSTPDirector._debug("handle_error %r", error)

    def indication(self, pdu):
        """Client requests are queued for delivery."""
        if _debug: MSTPDirector._debug("indication %r", pdu)

        # get the destination
        addr = pdu.pduDestination

        # get the peer
        peer = self.peers.get(addr, None)
        if not peer:
            peer = self.actorClass(self, addr)

        # send the message
        peer.indication(pdu)

    def _response(self, pdu):
        """Incoming datagrams are routed through an actor."""
        if _debug: MSTPDirector._debug("_response %r", pdu)

        # get the destination
        addr = pdu.pduSource

        # get the peer
        peer = self.peers.get(addr, None)
        if not peer:
            peer = self.actorClass(self, addr)

        # send the message
        peer.response(pdu)
#
#   MSTPMultiplexer
#

@bacpypes_debugging
class MSTPMultiplexer:

    def __init__(self, localDevice, addr=None, noBroadcast=False):
        if _debug: MSTPMultiplexer._debug("__init__ %r noBroadcast=%r", addr, noBroadcast)

        self.address = addr
        self.localDevice = localDevice

        # create and bind the direct address
        self.direct = _MultiplexClient(self)
        self.directPort = MSTPDirector(self.localDevice, self.address)
        bind(self.direct, self.directPort)

        # create and bind the Annex H and J servers
        self.annexH = _MultiplexServer(self)

    def close_socket(self):
        if _debug: MSTPMultiplexer._debug("close_socket")

        # pass along the close to the director(s)
        self.directPort.close_socket()

    def indication(self, server, pdu):
        if _debug: MSTPMultiplexer._debug("indication %r %r", server, pdu)

        # check for a broadcast message
        if pdu.pduDestination.addrType == Address.localBroadcastAddr:
            dest = 255
            if _debug: MSTPMultiplexer._debug("    - requesting local broadcast: %r", dest)

            # interface might not support broadcasts
            if not dest:
                return

        elif pdu.pduDestination.addrType == Address.localStationAddr:
            dest = pdu.pduDestination
            if _debug: MSTPMultiplexer._debug("    - requesting local station: %r", dest)

        else:
            raise RuntimeError("invalid destination address type")

        self.directPort.indication(PDU(pdu, destination=dest))

    def confirmation(self, client, pdu):
        if _debug: MSTPMultiplexer._debug("confirmation %r %r", client, pdu)

        # if this came from ourselves, dump it
        self.addrTuple = None
        if pdu.pduSource == self.address:
            if _debug: MSTPMultiplexer._debug("    - from us!")
            return

        src = pdu.pduSource

        # match the destination in case the stack needs it
        if client is self.direct:
            dest = self.address
        elif client is self.broadcast:
            dest = LocalBroadcast()
        else:
            raise RuntimeError("confirmation mismatch")

        # must have at least one octet
        if not pdu.pduData:
            if _debug: MSTPMultiplexer._debug("    - no data")
            return

        try:
            pdu.pduExpectingReply = False
            pdu.pduNetworkPriority = 0
            self.annexH.response(pdu)
        except Exception as e:
            MSTPMultiplexer._error('Exception in confirmation {}'.format(e))

@bacpypes_debugging
class MSTPSimpleApplication(ApplicationIOController, WhoIsIAmServices, ReadWritePropertyServices):

    def __init__(self, localDevice, localAddress, deviceInfoCache=None, aseID=None):
        if _debug: MSTPSimpleApplication._debug("__init__ %r %r deviceInfoCache=%r aseID=%r", localDevice, localAddress, deviceInfoCache, aseID)
        ApplicationIOController.__init__(self, localDevice, deviceInfoCache, aseID=aseID)

        # local address might be useful for subclasses
        if isinstance(localAddress, Address):
            self.localAddress = localAddress
        else:
            self.localAddress = Address(localAddress)

        self.localDevice = localDevice

        # include a application decoder
        self.asap = ApplicationServiceAccessPoint()

        # pass the device object to the state machine access point so it
        # can know if it should support segmentation
        self.smap = StateMachineAccessPoint(localDevice)

        # the segmentation state machines need access to the same device
        # information cache as the application
        self.smap.deviceInfoCache = self.deviceInfoCache

        # a network service access point will be needed
        self.nsap = NetworkServiceAccessPoint()

        # give the NSAP a generic network layer service element
        self.nse = NetworkServiceElement()
        bind(self.nse, self.nsap)

        # bind the top layers
        bind(self, self.asap, self.smap, self.nsap)

        # create a generic MSTP stack, bound to the Annex J server
        # on the MSTP multiplexer
        self.mstp = MSTPSimple()
        self.mux = MSTPMultiplexer(self.localDevice, self.localAddress)

        # bind the bottom layers
        bind(self.mstp, self.mux.annexH)

        # bind the MSTP stack to the network, no network number
        self.nsap.bind(self.mstp)

    def close_socket(self):
        if _debug: MSTPSimpleApplication._debug("close_socket")

        # pass to the multiplexer, then down to the sockets
        self.mux.close_socket()

