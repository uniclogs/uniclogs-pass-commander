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

"""
  Todo:
    - parse paramaters for testing
      - without hardware
      - low-gain TX
    - verify doppler
    - add a mode for decoding arbitrary sats, then test
"""

from time import sleep
import ephem
from math import degrees as deg
from apscheduler.schedulers.background import BackgroundScheduler
import sys
import re
import os
import pydbus
import logging as log
import configparser
import json
from functools import reduce
import operator

sys.path.append(os.path.dirname(__file__))
from Rotator import Rotator
from Navigator import Navigator
from Tracker import Tracker
from Radio import Radio
from Station import Station


# Config File
config_file = os.path.expanduser("~/.config/OreSat/pass_commander.ini")
config = configparser.ConfigParser()
if not len(config.read(config_file)):
    print("Config file seems to be missing. Initializing.")
    if not os.path.exists(os.path.dirname(config_file)):
        os.makedirs(os.path.dirname(config_file))
    with open(config_file, "w") as f:
        f.write(
            """# Be sure to replace all <hint text> including the angle brackets!
[Main]
owmid = <open weather map API key>
edl = <EDL command to send, hex formatted with no 0x prefix>
txgain = 47

[Hosts]
radio = 127.0.0.2
station = 127.0.0.1
rotator = 127.0.0.1

[Observer]
lat = <latitude in decimal notation>
lon = <longitude in decimal notation>
alt = <altitude in meters>
name = <station name or callsign>
"""
        )
    print(f"Please edit {config_file} before running again.")
    sys.exit(1)

if '<' in [v[0] for s in config.keys() for v in config[s].values()]:
    print(f"Please edit {config_file} and replace everything in <angle brackets>")
    sys.exit(1)

# This is just shoehorned in here and ugly. Please fix!
def confget(conf, tree):
    try:
        return reduce(operator.getitem, tree, conf)
    except KeyError:
        print(f"Configuration element missing: {tree[0]}")
        sys.exit(2)


host_radio = confget(config, ["Hosts", "radio"])
host_station = confget(config, ["Hosts", "station"])
host_rotator = confget(config, ["Hosts", "rotator"])
observer = [
    confget(config, ["Observer", "lat"]),
    confget(config, ["Observer", "lon"]),
    int(confget(config, ["Observer", "alt"])),
]

# sat_id can be International Designator, Catalog Number, or Name
sat_id = "OreSat0"
pass_count = 9999  # Maximum number of passes to operate before shutting down
if len(sys.argv) > 1:
    if re.match(r"\d{1,2}$", sys.argv[1]):
        pass_count = int(sys.argv[1])
    else:
        sat_id = sys.argv[1]

az_cal, el_cal = 0, 0
owmid = confget(config, ["Main", "owmid"])
edl_packet = confget(config, ["Main", "edl"])
local_only = False
no_tx = False
no_rot = False
tx_gain = int(confget(config, ["Main", "txgain"]))
if len(edl_packet) <= 10:
    print('Not going to TX because no EDL bytes have been defined')
    no_tx = True

# XXX These should be set by command line arguments
# local_only=True # XXX Test mode with no connections
# no_tx=True  # XXX
# no_rot=True  # XXX

tle_cache = {}
tle_cache_file = os.path.expanduser("~/.config/OreSat/tle_cache.json")
if os.path.isfile(tle_cache_file):
    with open(tle_cache_file, "r") as jsonfile:
        tle_cache = json.load(jsonfile)

log.basicConfig()
log.getLogger("apscheduler").setLevel(log.ERROR)


class Main:
    def __init__(
        self,
        o_tracker=Tracker(observer,
            sat_id=sat_id,
            local_only=local_only,
            tle_cache=tle_cache,
            owmid=owmid,
        ),
        o_rotator=Rotator(
            host_rotator,
            az_cal=az_cal,
            el_cal=el_cal,
            local_only=local_only,
            no_rot=no_rot,
        ),
        o_radio=Radio(host_radio, local_only=local_only),
        o_station=Station(host_station, no_tx=no_tx),
        o_scheduler=BackgroundScheduler(),
    ):
        self.track = o_tracker
        self.rot = o_rotator
        self.rad = o_radio
        self.sta = o_station
        self.scheduler = o_scheduler
        self.scheduler.start()
        self.nav = None

    def NTPSynchronized(self):
        return pydbus.SystemBus().get(".timedate1").NTPSynchronized

    def require_clock_sync(self):
        while not self.NTPSynchronized():
            print("System clock is not synchronized. Sleeping 60 seconds.")
            sleep(60)
        print("System clock is synchronized.")

    def edl(self, packet):
        self.rad.command(
            "set_gpredict_tx_frequency",
            self.rad.txfreq - self.track.freshen().doppler(self.rad.txfreq),
        )
        self.rad.edl(packet)

    def autorun(self, count=9999):
        print(f"Running for {count} passes")
        while count > 0:
            self.require_clock_sync()
            np = self.track.sleep_until_next_pass()
            self.nav = Navigator(self.track, *np)
            self.work_pass()
            seconds = (np[4] - ephem.now()) / ephem.second + 1
            if seconds > 0:
                print(f"Sleeping {seconds:.3f} seconds until pass is really over.")
                sleep(seconds)
            count -= 1

    def work_pass(self, packet=edl_packet):
        if local_only:
            return self.test_bg_rotator()
        degc = self.sta.gettemp()
        if degc > 30:
            print(f"Temperature is too high ({degc}°C). Skipping this pass.")
            sleep(1)
            return
        self.packet = b''
        if not no_tx:
            self.packet = bytes.fromhex(packet)
        print("Packet to send: ", self.packet)
        self.track.calibrate()
        print("Adjusted for temp/pressure")
        self.update_rotator()
        print("Started rotator movement")
        sleep(2)
        self.scheduler.add_job(self.update_rotator, "interval", seconds=0.5)
        print("Scheduled rotator")
        self.rad.command("set_tx_selector", "edl")
        print("Selected EDL TX")
        self.rad.command("set_tx_gain", tx_gain)
        print("Set TX gain")
        sleep(2)
        print("Rotator should be moving by now")
        while self.rot.share["moving"] == True:
            sleep(0.1)
        if self.rot.share["moving"]:
            print("Rotator communication anomaly detected. Skipping this pass.")
            self.scheduler.remove_all_jobs()
            sleep(1)
            return
        print("Stopped moving")
        self.sta.pa_on()
        print("Station amps on")
        sleep(0.2)
        self.sta.ptt_on()
        print("Station PTT on")
        self.rad.ident()
        print("Sent Morse ident")
        self.sta.ptt_off()
        print("Station PTT off")
        print("Waiting for bird to reach 10°el")
        while self.track.share["target_el"] < 10:
            sleep(0.1)
        print("Bird above 10°el")
        while self.track.share["target_el"] >= 10:
            if no_tx:
                sleep(0.5)
            else:
                self.sta.ptt_on()
                print("Station PTT on")
                self.edl(self.packet)
                print("Sent EDL")
                # FIXME TIMING: wait for edl to finish sending
                sleep(0.5)
                self.sta.ptt_off()
                print("Station PTT off")
            sleep(3.5)
        self.scheduler.remove_all_jobs()
        print("Removed scheduler jobs")
        self.sta.ptt_on()
        print("Station PTT on")
        self.rad.ident()
        print("Sent Morse ident")
        self.sta.ptt_off()
        print("Station PTT off")
        self.rad.command("set_tx_gain", 3)
        print("Set TX gain to min")
        self.rot.park()
        print("Parked rotator")
        print("Waiting for PA to cool")
        sleep(120)
        self.sta.pa_off()
        print("Station shutdown TX amp")

    def update_rotator(self):
        azel = self.nav.azel(self.track.freshen().azel())
        if not local_only:
            self.rot.go(*tuple(deg(x) for x in azel))
            self.rad.command(
                "set_gpredict_rx_frequency",
                self.track.doppler(self.rad.rxfreq) - self.rad.rxfreq,
            )

    """ Testing stuff goes below here """

    def dryrun_time(self):
        self.track.obs.date = self.track.obs.date + (30 * ephem.second)
        self.track.sat.compute(self.track.obs)
        azel = self.nav.azel(self.track.azel())

    def dryrun(self):
        np = self.track.get_next_pass(80)
        self.nav = Navigator(self.track, *np)
        self.track.obs.date = np[0]
        self.scheduler.add_job(self.dryrun_time, "interval", seconds=0.2)
        sleep(4.5)
        self.scheduler.remove_all_jobs()

    def test_rotator(self):
        while True:
            print(self.update_rotator())
            sleep(0.1)

    def test_bg_rotator(self):
        self.scheduler.add_job(self.update_rotator, "interval", seconds=0.5)
        while True:
            sleep(1000)
            # print(self.rot.share['moving'])

    def test_doppler(self):
        while True:
            print(self.track.freshen().doppler())
            sleep(0.1)

    def test_morse(self):
        while True:
            self.rad.ident()
            sleep(30)


def main():
    Main().autorun(pass_count)
    # Tests could include things like:
    # Main().dryrun()
    # Main().test_doppler()
    # Main().track.sleep_until_next_pass()


if __name__ == "__main__":
    main()
