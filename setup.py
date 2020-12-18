"""
Copyright (c) 2018 by Riptide I/O
All rights reserved.
"""

import os
import sys

from setuptools import setup
from wheel.bdist_wheel import bdist_wheel


class BinaryDistWheel(bdist_wheel):
    def finalize_options(self):
        bdist_wheel.finalize_options(self)
        self.root_is_pure = False


# This creates a list which is empty but returns a length of 1.
# Should make the wheel a binary distribution and platlib compliant.
class EmptyListWithLength(list):
    def __len__(self):
        return 1


def setup_packages():

    long_description = (
        "The misty package helps build bacpypes Applications"
        " that work on MS/TP Networks. The BIP (BACnet IP ) "
        "Applications can be easily ported to use misty."
    )

    meta_data = dict(
        name="misty",
        version='0.0.10',
        description='MSTP support for bacpypes',
        scripts=[
            'bin/CommandableMixin',
            'bin/ReadProperty',
            'bin/ReadPropertyMultiple',
            'bin/ReadPropertyMultipleServer',
            'bin/ReadWriteProperty',
            'bin/WhoIsIAm',
            'bin/bc',
            'bin/bs',
            'bin/cp_ini'
        ],
        long_description=long_description,
        license='GNU General Public License v2.0',
        author='Riptide, Inc',
        author_email='raghavan@riptideio.com',
        maintainer='Riptide, Inc',
        maintainer_email='raghavan@riptideio.com',
        url='https://github.com/riptideio/misty',
        zip_safe=False,
        cmdclass={'bdist_wheel': BinaryDistWheel},
        package_dir={
            'misty': 'misty'
        },
        package_data={
            'misty': [
                'mstplib/libmstp_agent.so'
            ]
        },
        packages=['misty', 'misty.mstplib'],
        data_files=[
            (
                (os.path.join(sys.prefix, 'cfg')),
                [
                    'misty/samples/bac_server.ini',
                    'misty/samples/bac_client.ini'
                ]
            )
        ],
        ext_modules=EmptyListWithLength(),
        install_requires=[
            "bacpypes>=0.18.0",
            "six>=1.15.0"
        ]
    )
    setup(**meta_data)


if __name__ == '__main__':
    setup_packages()
