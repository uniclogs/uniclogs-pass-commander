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
from time import sleep
import re


class Station:
    def __init__(self, host, station_port=5005, band="l-band", no_tx=False):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = (host, station_port)
        self.band = band
        self.no_tx = no_tx

    def command(self, verb):
        if self.no_tx and re.search(r"pa-power|rf-ptt", verb):
            print("Not sending command: ", verb)
            return ''
        if re.match(
            r"^(gettemp|((l-band|uhf) (pa-power|rf-ptt)|rotator) (on|off|status))$",
            verb,
        ):
            print(f"Sending command: {verb}")
            self.s.sendto((verb).encode(), self.addr)
            return self.response()

    def commands(self, *verbs):
        for v in verbs:
            ret = self.command(v)
            sleep(0.1)
        return ret

    def response(self):
        data, addr = self.s.recvfrom(4096)
        stat = data.decode().strip()
        print(f"StationD response: {stat}")
        return stat

    def pa_on(self):
        self.command(f"{self.band} pa-power on")
        return self.command(f"{self.band} pa-power on")

    def pa_off(self):
        ret = self.command(f"{self.band} pa-power off")
        if re.search(r"PTT Conflict", ret):
            self.pa_off()
            sleep(120)
            return self.pa_off()
        elif m := re.search(r"Please wait (\S+) seconds", ret):
            sleep(int(m.group(1)))
            return self.pa_off()
        return ret

    def ptt_on(self):
        ret = self.command(f"{self.band} rf-ptt on")
        # FIXME TIMING: wait for PTT to open (100ms is just a guess)
        sleep(0.1)
        return ret

    def ptt_off(self):
        return self.command(f"{self.band} rf-ptt off")

    def gettemp(self):
        ret = self.command("gettemp")
        return float(ret[6:].strip())
