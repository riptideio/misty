#!/usr/bin/env python

import sys
import os
import argparse

bac_client_ini = """[BACpypes]
objectName: BACClient
address: 25
interface:/var/tmp/ttyp0
max_masters: 127
baudrate: 38400
maxinfo:1
objectIdentifier: 599
maxApduLengthAccepted: 1024
segmentationSupported: segmentedBoth
vendorIdentifier: 15
foreignPort: 0
foreignBBMD: 128.253.109.254
foreignTTL: 30
; enable this to see the mstp debug logs
; mstpdbgfile:/home/riptide/abcd.log
"""

bac_server_ini="""[BACpypes]
objectName: BACServer
address: 30
interface:/var/tmp/ptyp0
max_masters: 127
baudrate: 38400
maxinfo:1
objectIdentifier: 699
maxApduLengthAccepted: 1024
segmentationSupported: segmentedBoth
vendorIdentifier: 15
foreignPort: 0
foreignBBMD: 128.253.109.254
foreignTTL: 30
"""


def handle_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-t", "--type", type=str,
        choices=['server', 'client'],
        help="ini file for bacnet server or client", default='client'
    )
    parser.add_argument(
        "path", help="dest path is where the ini file would be copied"
    )
    args = parser.parse_args()

    return args.type, args.path

def write_file(fname, ini_type):
    with open(fname, "w") as fd:
        if ini_type == "server":
            content = bac_server_ini
        else:
            content = bac_client_ini

        fd.write(content)




def main():

    fname_dict = {
        "server" : 'bac_server.ini',
        "client" : 'bac_client.ini'
    }

    ini_type, dest = handle_args()

    dest = os.path.abspath(dest)
    fname = fname_dict[ini_type]

    if os.path.isdir(dest):
        dest = os.path.join(dest, fname)

    write_file(dest, ini_type)

    print("copied the ini file to '{}' ".format(dest))


if __name__ == "__main__":
    main()
