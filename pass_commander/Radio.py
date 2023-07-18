#!/usr/bin/env python3
#
# Copyright (c) 2022-2023 Kenny M.
#
# This file is part of UniClOGS Pass Commander
# (see https://github.com/uniclogs/uniclogs-pass_commander).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#


import socket
from threading import Lock
from xmlrpc.client import ServerProxy
from time import sleep


class Radio:
    def __init__(self, host, xml_port=10080, edl_port=10025, local_only=False):
        self.edl_addr = (host, edl_port)
        self.xml_addr = (host, xml_port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.lock = Lock()
        self.xo = ServerProxy("http://%s:%i" % self.xml_addr)
        if not local_only:
            self.txfreq = self.xo.get_tx_center_frequency()
            self.rxfreq = self.xo.get_rx_target_frequency()

    def ident(self):
        old_selector = self.xo.get_tx_selector()
        self.xo.set_tx_selector("morse")
        self.xo.set_morse_bump(self.xo.get_morse_bump() ^ 1)
        sleep(4)
        self.xo.set_tx_selector(old_selector)
        return self.xo

    def command(self, func, *args):
        with self.lock:
            # With the locking, a shared ServerProxy object should be fine, but no.
            xo = ServerProxy("http://%s:%i" % self.xml_addr)
            ret = xo.__getattr__(func)(*args)
        return ret

    def edl(self, packet):
        self.s.sendto(packet, self.edl_addr)
