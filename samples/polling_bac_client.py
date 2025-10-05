import time
import argparse
import ipaddress
import random
import logging
import pprint
import csv

from collections import deque

from misty.mstplib import MSTPSimpleApplication

from bacpypes.local.device import LocalDeviceObject
from bacpypes.pdu import GlobalBroadcast
from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.task import RecurringTask
from bacpypes.primitivedata import (
    Null,
    Atomic,
    Boolean,
    Unsigned,
    Integer,
    Real,
    Double,
    OctetString,
    CharacterString,
    BitString,
    Date,
    Time,
    ObjectIdentifier,
)
from bacpypes.constructeddata import Array, Any, AnyAtomic

from bacpypes.core import run, deferred
from bacpypes.iocb import IOCB
from bacpypes.object import get_datatype

from bacpypes.errors import DecodingError

from bacpypes.constructeddata import ArrayOf

from bacpypes.pdu import Address
from bacpypes.apdu import ReadPropertyRequest, ReadPropertyACK
from bacpypes.apdu import SimpleAckPDU, WritePropertyRequest

from bacpypes.pdu import LocalBroadcast

from bacpypes.apdu import (
    IAmRequest,
    ReadPropertyMultipleRequest,
    PropertyReference,
    ReadAccessSpecification,
    ReadPropertyMultipleACK,
)

# some debugging
_debug = 0
_log = ModuleLogger(globals())

logger = logging.getLogger(__name__)

# convenience definition
ArrayOfObjectIdentifier = ArrayOf(ObjectIdentifier)

#
#   ObjectListContext
#


class ObjectListContext:

    def __init__(self, device_id, device_addr, object_list=[]):
        self.device_id = device_id
        self.device_addr = device_addr

        self.object_list = object_list
        self.object_names = []
        self._object_list_queue = None
        if object_list:
            self._object_list_queue = deque(object_list)

    def completed(self, had_error=None):
        if had_error:
            logger.info("had error: %r" % (had_error,))
        else:
            pass


class PulseTask(RecurringTask):
    def __init__(self, app, interval=None, offset=None):
        super().__init__(interval, offset)
        self.install_task()
        self.app = app

    def process_task(self):
        self.app.fetch_values()
        pprint.pprint("DEVICE_DB")
        pprint.pprint(self.app.device_db)
        pprint.pprint("SNAPSHOT")
        pprint.pprint(self.app.values_dict)
        self.app.write_values_to_csv("snapshot.csv")


#
#   ReadObjectListApplication
#


@bacpypes_debugging
class BACnetClientApplication(MSTPSimpleApplication):

    def __init__(self, localDevice=None, localAddress=None):
        MSTPSimpleApplication.__init__(
            self, localDevice=localDevice, localAddress=localAddress
        )
        self.localDevice = None
        self.interested_obj_types = {
            "analogValue": True,
            "analogInput": True,
            "binaryInput": True,
            "binaryOutput": True,
            "analogOutput": True,
            "binaryValue": True,
            "multiStateValue": True,
            "multiStateOutput": True,
            "multiStateInput": True,
            "characterstringValue": True,
        }

        # device_db = {
        #     234: {
        #         'address': '192.168.1.8',
        #         'maxAPDULengthAccepted': 1476,
        #         'object_list': [
        #             ('device', 234),
        #             ('networkPort', 1),
        #             ('analogInput', 1),
        #             ('analogOutput', 1),
        #             ('analogValue', 1),
        #             ('binaryInput', 1)
        #         ]
        #     }
        # }
        self.device_db = {}

        # values_dict={
        #     234: {
        #         ('analogOutput', 1): {
        #             'covIncrement': 1.0,
        #             'currentCommandPriority': {'null': ()},
        #             'description': '',
        #             'eventState': 'normal',
        #             'maxPresValue': 100.0,
        #             'minPresValue': 0.0,
        #             'objectIdentifier': ('analogOutput', 1),
        #             'objectName': 'ANALOG OUTPUT 1',
        #             'objectType': 'analogOutput',
        #             'outOfService': False,
        #             'presentValue': 0.0
        #         }
        #     }
        # }

        self.values_dict = {}

    def request(self, apdu):
        # forward it along
        MSTPSimpleApplication.request(self, apdu)

    def indication(self, apdu):
        # The response to WhoIs is IAmRequest from each of
        # the devices
        if isinstance(apdu, IAmRequest):
            self.process_IAmRequest(apdu)

        MSTPSimpleApplication.indication(self, apdu)

    def process_IAmRequest(self, apdu):
        device_type, device_instance = apdu.iAmDeviceIdentifier
        if device_type != "device":
            raise DecodingError("invalid object type")

        device_id = apdu.iAmDeviceIdentifier[1]
        if device_id not in self.device_db:
            self.device_db[device_id] = {}

        device_db = self.device_db[device_id]
        device_db["maxAPDULengthAccepted"] = apdu.maxAPDULengthAccepted
        device_db["segmentationSupported"] = apdu.segmentationSupported
        device_db["vendorID"] = apdu.vendorID
        device_db["address"] = apdu.pduSource.dict_contents()
        device_db["object_list_complete"] = False

        if "object_list" not in device_db:
            device_address = device_db["address"]
            self.get_obj_list_for_device(
                device_id=device_id, device_address=device_address
            )

    def confirmation(self, apdu):
        # forward it along
        MSTPSimpleApplication.confirmation(self, apdu)

    def make_rp_for_obj_list(self, device_id, device_addr):

        # create a context to hold the results
        context = ObjectListContext(device_id, device_addr)
        context.index_0_checked = False

        # property array index 0 has the length of object list
        request = ReadPropertyRequest(
            destination=context.device_addr,
            objectIdentifier=context.device_id,
            propertyIdentifier="objectList",
            propertyArrayIndex=0,
        )

        # make an IOCB, reference the context
        iocb = IOCB(request)
        iocb.context = context

        # let us know when its complete
        iocb.add_callback(self.handle_response_for_obj_list)

        # give it to the application
        self.request_io(iocb)

    def handle_response_for_obj_list(self, iocb):

        # extract the context
        context = iocb.context

        # do something for error/reject/abort
        if iocb.ioError:
            context.completed(iocb.ioError)
            return

        # do something for success
        apdu = iocb.ioResponse

        # should be an ack
        if not isinstance(apdu, ReadPropertyACK):
            context.completed(RuntimeError("read property ack expected"))
            return

        if apdu.propertyArrayIndex == 0:
            context.expected_count = apdu.propertyValue.cast_out(Unsigned)
            context.index_0_checked = True
            request = ReadPropertyRequest(
                destination=context.device_addr,
                objectIdentifier=context.device_id,
                propertyIdentifier="objectList",
                propertyArrayIndex=None,
            )
            new_iocb = IOCB(request)
            new_iocb.context = context
            new_iocb.add_callback(self.handle_response_for_obj_list)
            deferred(self.request_io, new_iocb)
            return

        # pull out the content
        object_list = apdu.propertyValue.cast_out(ArrayOfObjectIdentifier)

        device_id = context.device_id[1]
        if device_id not in self.device_db:
            self.device_db[device_id] = {}

        self.device_db[device_id]["object_list"] = object_list

        if context.index_0_checked:
            count = len(object_list)
            print(f"Object list count = {count}, expected = {context.expected_count}")
            if count == context.expected_count:
                self.device_db[device_id]["object_list_complete"] = True
                print("object list complete")
                self.get_values_for_device(
                    device_id=device_id,
                    device_address=self.device_db[device_id]["address"],
                    object_list=object_list,
                )
            else:
                print("Warning: object list may be incomplete")


    def get_values_for_device(self, device_id, device_address, object_list):
        dev_id = ("device", device_id)
        dev_addr = Address(device_address)
        trim_list = self.trim_obj_list(object_list)
        if trim_list:
            context = ObjectListContext(dev_id, dev_addr, trim_list)
            deferred(self.read_next_object, context)

    def get_obj_list_for_device(self, device_id, device_address):
        dev_id = ("device", device_id)
        dev_addr = Address(device_address)
        deferred(self.make_rp_for_obj_list, dev_id, dev_addr)

    def trim_obj_list(self, obj_list):
        trim_list = []
        for entry in obj_list:
            (obj_type, inst_no) = entry
            if obj_type in self.interested_obj_types:
                trim_list.append(entry)
        return trim_list

    def write_values_to_csv(self, csv_filename):
        """
        Writes a snapshot of all point values to CSV.
        Only includes selected fields in a fixed order.
        Overwrites the file each time it's called.
        """
        fieldnames = [
            "device_id",
            "objectName",
            "description",
            "objectType",
            "instance_number",
            "presentValue",
            "units",
        ]

        rows = []
        for device_id, obj_map in self.values_dict.items():
            for (obj_type, instance_no), prop_map in obj_map.items():
                row = {
                    "device_id": device_id,
                    "instance_number": instance_no,
                }
                for key in ("objectName", "description", "objectType", "presentValue", "units"):
                    row[key] = prop_map.get(key, "")
                rows.append(row)

        with open(csv_filename, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Wrote {len(rows)} records to {csv_filename}")

    def fetch_values(self):
        logger.info("fetch values begins for BACnet interface")
        a = pprint.pformat(self.device_db, indent=4)
        b = pprint.pformat(self.values_dict, indent=4)

        logger.debug(f"device_db = \n{a}\n" f"values_dict= \n{b}\n")

        self.who_is(address=GlobalBroadcast())

        for device_id in self.device_db:
            device_dict = self.device_db[device_id]
            device_address = device_dict["address"]
            if "object_list" in device_dict:
                object_list = device_dict["object_list"]
                self.get_values_for_device(
                    device_id=device_id,
                    device_address=device_address,
                    object_list=object_list,
                )
        logger.info("fetch values for BACnet ends")

    def read_next_object(self, context):

        # if there's nothing more to do, we're done
        if not context._object_list_queue:
            context.completed()
            return

        # pop off the next object identifier
        object_id = context._object_list_queue.popleft()

        prop_reference_list = []
        read_access_spec_list = []
        prop_reference = PropertyReference(
            propertyIdentifier="all",
        )
        prop_reference_list.append(prop_reference)

        # build a read access specification
        read_access_spec = ReadAccessSpecification(
            objectIdentifier=object_id,
            listOfPropertyReferences=prop_reference_list,
        )
        read_access_spec_list.append(read_access_spec)

        request = ReadPropertyMultipleRequest(
            listOfReadAccessSpecs=read_access_spec_list,
        )
        request.pduDestination = context.device_addr

        # make an IOCB, reference the context
        iocb = IOCB(request)
        iocb.context = context

        # let us know when its complete
        iocb.add_callback(self.all_props_results)

        # give it to the application
        self.request_io(iocb)

    def all_props_results(self, iocb):
        try:
            self._all_props_results(iocb)
        except Exception as e:
            logger.exception(e)

        # extract the context
        context = iocb.context

        # read the next one
        deferred(self.read_next_object, context)

    def _all_props_results(self, iocb):

        # extract the context
        context = iocb.context

        # do something for error/reject/abort
        if iocb.ioError:
            logger.warning(str(iocb.ioError) + "\n")

        # do something for success
        if not iocb.ioResponse:
            return

        apdu = iocb.ioResponse

        # should be an ack
        if not isinstance(apdu, ReadPropertyMultipleACK):
            return

        device_id = context.device_id[1]

        if device_id not in self.values_dict:
            self.values_dict[device_id] = {}

        # loop through the results
        for result in apdu.listOfReadAccessResults:
            # here is the object identifier
            objectIdentifier = result.objectIdentifier
            obj_prop_values_dict = {}
            self.values_dict[device_id][
                objectIdentifier
            ] = obj_prop_values_dict

            # now come the property values per object
            for element in result.listOfResults:
                # get the property and array index
                propertyIdentifier = element.propertyIdentifier
                propertyArrayIndex = element.propertyArrayIndex

                # here is the read result
                readResult = element.readResult

                try:
                    if propertyArrayIndex is not None:
                        pass

                    # check for an error
                    if readResult.propertyAccessError is not None:
                        pass

                    else:
                        # here is the value
                        propertyValue = readResult.propertyValue

                        # find the datatype
                        datatype = get_datatype(
                            objectIdentifier[0], propertyIdentifier
                        )
                        if not datatype:
                            value = "?"
                        else:
                            # special case for array parts,
                            # others are managed by cast_out
                            if issubclass(datatype, Array) and (
                                propertyArrayIndex is not None
                            ):
                                if propertyArrayIndex == 0:
                                    value = propertyValue.cast_out(Unsigned)
                                else:
                                    value = propertyValue.cast_out(
                                        datatype.subtype
                                    )
                            else:
                                value = propertyValue.cast_out(datatype)

                        if isinstance(value, list):
                            if value:
                                elem = value[0]
                                if hasattr(elem, "dict_contents"):
                                    nvalue = [
                                        elem.dict_contents() for elem in value
                                    ]
                                    value = nvalue
                        elif hasattr(value, "dict_contents"):
                            value = value.dict_contents()
                        elif isinstance(value, float):
                            value = round(value,2)

                        obj_prop_values_dict[propertyIdentifier] = value
                except Exception as e:
                    pass

        # use the activeText and inactiveText as values
        d = obj_prop_values_dict
        if d["objectType"].startswith('binary'):
            if "presentValue" not in d:
                return
            active_text = d.get("activeText")
            inactive_text = d.get("inactiveText")
            value = d["presentValue"]
            if value == 'active':
                value = active_text
            else:
                value = inactive_text
            d["presentValue"] = value


    def who_is(self, low_limit=None, high_limit=None, address=None):
        if address is None:
            address = LocalBroadcast()
        super().who_is(low_limit, high_limit, address)

    def get_address_for_device_id(self, device_id):
        if device_id not in self.device_db:
            return None
        device_db = self.device_db[device_id]
        address = device_db.get("address")
        return address

    def write_property(
        self,
        device_id,  # e.g. 123 or 456
        obj_type,  # "analogValue", "analogOutput"
        instance_no,  # 1, 2
        prop_id,  # presentValue, priorityArray
        value,  # 100.45
        indx=None,  #
        priority=None,  # 1, 2
    ):
        try:
            logger.info(
                f"Write property called with device_id={device_id}"
                f"{obj_type} {instance_no} {prop_id} {value} {indx}"
                f"{priority}"
            )
            self._write_property(
                device_id,
                obj_type,
                instance_no,
                prop_id,
                value,
                indx,
                priority,
            )
        except Exception as e:
            logger.exception(e)

        return value

    def _write_property(
        self,
        device_id,
        obj_type,
        instance_no,
        prop_id,
        value,
        indx=None,
        priority=None,
    ):
        # write 172.17.0.3 analogValue:0 presentValue 35
        addr = self.get_address_for_device_id(device_id)

        # get the datatype
        datatype = get_datatype(obj_type, prop_id)

        obj_id = (obj_type, instance_no)

        # change atomic values into something encodeable,
        # null is a special case
        if value is None:
            value = Null()
        elif issubclass(datatype, AnyAtomic):
            dtype, dvalue = value.split(":", 1)

            datatype = {
                "b": Boolean,
                "u": lambda x: Unsigned(int(x)),
                "i": lambda x: Integer(int(x)),
                "r": lambda x: Real(float(x)),
                "d": lambda x: Double(float(x)),
                "o": OctetString,
                "c": CharacterString,
                "bs": BitString,
                "date": Date,
                "time": Time,
                "id": ObjectIdentifier,
            }[dtype]

            value = datatype(dvalue)

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
                raise TypeError(
                    "invalid result datatype, expecting %s"
                    % (datatype.subtype.__name__,)
                )
        elif not isinstance(value, datatype):
            raise TypeError(
                "invalid result datatype, expecting %s" % (datatype.__name__,)
            )

        logger.info(f"addr={addr} datatype={datatype} value={value}")

        # build a request
        request = WritePropertyRequest(
            objectIdentifier=obj_id, propertyIdentifier=prop_id
        )
        request.pduDestination = Address(addr)

        # save the value
        request.propertyValue = Any()
        try:
            request.propertyValue.cast_in(value)
        except Exception as error:
            logger.exception(error)

        # optional array index
        if indx is not None:
            request.propertyArrayIndex = indx

        # optional priority
        if priority is not None:
            request.priority = priority

        # make an IOCB
        iocb = IOCB(request)

        iocb.add_callback(self.handle_write_prop_cb)

        # give it to the application
        deferred(self.request_io, iocb)

    def handle_write_prop_cb(self, iocb):
        logger.info("WriteProperty callback")
        try:
            # do something for success
            if iocb.ioResponse:
                # should be an ack
                if not isinstance(iocb.ioResponse, SimpleAckPDU):
                    return

                logger.info("ack\n")

            # do something for error/reject/abort
            if iocb.ioError:
                logger.warning(str(iocb.ioError) + "\n")

        except Exception as error:
            logger.exception(error)

    def start(self):
        deferred(run)

    def get_value_for_prop(self, device_id, obj_id, instance_no, prop_id):
        if device_id not in self.values_dict:
            return None
        device_values = self.values_dict[device_id]
        obj_id_tup = (obj_id, instance_no)
        if obj_id_tup not in device_values:
            return None
        prop_values_dict = device_values[obj_id_tup]
        if prop_id not in prop_values_dict:
            return None
        return prop_values_dict[prop_id]

    def set_value_for_prop(
        self, device_id, obj_id, instance_no, prop_id, value
    ):
        if device_id not in self.values_dict:
            return None
        device_values = self.values_dict[device_id]
        obj_id_tup = (obj_id, instance_no)
        if obj_id_tup not in device_values:
            return None
        prop_values_dict = device_values[obj_id_tup]
        if prop_id not in prop_values_dict:
            return None
        logger.info(f"setting prop_id={prop_id} value={value}")
        prop_values_dict[prop_id] = value

    def get_values_for_all_props(self, device_id, obj_id, instance_no):
        if device_id not in self.values_dict:
            return None
        device_values = self.values_dict[device_id]
        obj_id_tup = (obj_id, instance_no)
        if obj_id_tup not in device_values:
            return None
        prop_values_dict = device_values[obj_id_tup]
        return prop_values_dict

    def run(self):
        while True:
            run()

    def get_device_db(self):
        device_db = {}
        device_db.update(self.device_db)
        return device_db

    def get_values_dict(self):
        values_dict = {}
        values_dict.update(self.values_dict)
        return values_dict

    def read_property(
        self,
        device_id=None,
        obj_type=None,
        instance_no=None,
        prop_id=None,
        indx=None,
        priority=None,
    ):

        logger.info("Read property called ")

        address = self.device_db[device_id]["address"]

        # Create request
        request = ReadPropertyRequest(
            objectIdentifier=(obj_type, instance_no),
            propertyIdentifier=prop_id,
        )

        if indx is not None:
            request.propertyArrayIndex = indx

        request.pduDestination = Address(address)

        # Create IOCB
        iocb = IOCB(request)
        iocb.context = {
            "device_id": device_id,
            "obj_id": obj_type,
            "instance_no": instance_no,
            "prop_id": prop_id,
        }

        # Add the callback to the IOCB
        iocb.add_callback(self.read_property_callback)

        # give it to the application
        deferred(self.request_io, iocb)

        return iocb

    def read_property_callback(self, iocb):

        # do something for error/reject/abort
        if iocb.ioError:
            return

        # do something for success
        apdu = iocb.ioResponse

        # should be an ack
        if not isinstance(apdu, ReadPropertyACK):
            return

        # Response was received
        apdu = iocb.ioResponse

        # find the datatype
        datatype = get_datatype(
            apdu.objectIdentifier[0], apdu.propertyIdentifier
        )

        # special case for array parts, others are managed by cast_out
        if issubclass(datatype, Array) and (
            apdu.propertyArrayIndex is not None
        ):
            if apdu.propertyArrayIndex == 0:
                value = apdu.propertyValue.cast_out(Unsigned)
            else:
                value = apdu.propertyValue.cast_out(datatype.subtype)
        else:
            value = apdu.propertyValue.cast_out(datatype)

        # Extract value
        logger.info(f"Read Callback received value: {value}")

        # Add your processing logic here
        context = iocb.context

        self.set_value_for_prop(**context, value=value)


#
#   __main__
#


def main():
    my_format = (
        "%(asctime)s|%(levelname)s|%(name)s:"
        "%(lineno)d|%(message)s"
    )
    logging.basicConfig(
        level=logging.INFO,
        format=my_format
    )

    parser = argparse.ArgumentParser(
        description="Example script for parsing address and interface."
    )

    parser.add_argument(
        "--address",
        type=int,
        default=25,
        help="Device address (default: 25)"
    )

    parser.add_argument(
        "--interface",
        type=str,
        default="/var/tmp/ttyp0",
        help="Device interface path (default: /var/tmp/ttyp0)"
    )

    parser.add_argument(
        "--baudrate",
        type=int,
        default=38400,
        help="baudrate (default: 38400)"
    )

    args = parser.parse_args()

    print(f"Address: {args.address}")
    print(f"Interface: {args.interface}")
    print(f"Baudrate: {args.baudrate}")


    # make a device object
    mstp_args = {
        '_address': args.address,
        '_interface': args.interface,
        '_max_masters': 127,
        '_baudrate': args.baudrate,
        '_maxinfo': 1
    }
    mstp_args["vendorIdentifier"] = 15
    mstp_args["objectIdentifier"] = 599

    # mstp_args['_mstpdbgfile'] = str(args.ini.mstpdbgfile)

    this_device = LocalDeviceObject(**mstp_args)

    # make a simple application
    app = BACnetClientApplication(this_device, args.address)
    app.start()
    PulseTask(app, interval=10 * 1000)
    run()


if __name__ == "__main__":
    main()

