#!/usr/bin/env python

import sys
import os
import shutil
import argparse


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


def main():

    fname_dict = {
        "server" : 'bac_server.ini',
        "client" : 'bac_client.ini'
    }

    ini_type, dest = handle_args()

    dest = os.path.abspath(dest)
    fname = fname_dict[ini_type]

    ini_file = os.path.join(sys.prefix, 'cfg', fname)
    shutil.copy(ini_file, dest)

    if os.path.isdir(dest):
        dest = os.path.join(dest, fname)

    print("copied the ini file to '{}' ".format(dest))


if __name__ == "__main__":
    main()
