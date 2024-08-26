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
from dataclasses import dataclass, field
from functools import reduce
from textwrap import dedent
from typing import Union
import operator

sys.path.append(os.path.dirname(__file__))
from Rotator import Rotator
from Navigator import Navigator
from Tracker import Tracker
from Radio import Radio
from Station import Station

@dataclass
class Config:
    # Main
    owmid: str
    edl: str
    txgain: int

    # Hosts
    radio: str
    station: str
    rotator: str

    # Observer
    lat: float
    lon: float
    alt: int
    name: str

    az_cal: int = 0
    el_cal: int = 0

    # Satellite
    sat_id: str = "OreSat0"
    tle_cache: dict[Union[list[str], bool]] = field(default_factory=dict)


def load_config_file(path):
    config_file = os.path.expanduser(path)
    config = configparser.ConfigParser()
    if not len(config.read(config_file)):
        print("Config file seems to be missing. Initializing.")
        if not os.path.exists(os.path.dirname(config_file)):
            os.makedirs(os.path.dirname(config_file))
        with open(config_file, "w") as f:
            f.write(dedent("""\
                # Be sure to replace all <hint text> including the angle brackets!
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
                """))
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

    return Config(
        owmid = confget(config, ["Main", "owmid"]),
        edl = confget(config, ["Main", "edl"]),
        txgain = int(confget(config, ["Main", "txgain"])),
        radio = confget(config, ["Hosts", "radio"]),
        station = confget(config, ["Hosts", "station"]),
        rotator = confget(config, ["Hosts", "rotator"]),
        lat = float(confget(config, ["Observer", "lat"])),
        lon = float(confget(config, ["Observer", "lon"])),
        alt = int(confget(config, ["Observer", "alt"])),
        name = confget(config, ["Observer", "name"]),
    )


def load_tle_cache(path):
    tle_cache_file = os.path.expanduser(path)
    if os.path.isfile(tle_cache_file):
        with open(tle_cache_file, "r") as jsonfile:
            return json.load(jsonfile)
    return { 'end': True }

class Main:
    def __init__(
        self,
        tracker,
        rotator,
        radio,
        station,
        scheduler,
    ):
        self.track = tracker
        self.rot = rotator
        self.rad = radio
        self.sta = station
        self.scheduler = scheduler
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

    def autorun(self, tx_gain, count=9999, packet=None, no_tx=False, local_only=False):
        print(f"Running for {count} passes")
        while count > 0:
            self.require_clock_sync()
            np = self.track.sleep_until_next_pass()
            self.nav = Navigator(self.track, *np)
            self.work_pass(tx_gain, packet, no_tx, local_only)
            seconds = (np[4] - ephem.now()) / ephem.second + 1
            if seconds > 0:
                print(f"Sleeping {seconds:.3f} seconds until pass is really over.")
                sleep(seconds)
            count -= 1

    def work_pass(self, tx_gain, edl_packet, no_tx, local_only):
        if local_only:
            return self.test_bg_rotator()
        degc = self.sta.gettemp()
        if degc > 30:
            print(f"Temperature is too high ({degc}°C). Skipping this pass.")
            sleep(1)
            return
        packet = b''
        if not no_tx:
            packet = bytes.fromhex(edl_packet)
        print("Packet to send: ", packet)
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
                self.edl(packet)
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
        self.rot.go(*tuple(deg(x) for x in azel))
        self.rad.command(
            "set_gpredict_rx_frequency",
            self.track.doppler(self.rad.rxfreq) - self.rad.rxfreq,
        )

    """ Testing stuff goes below here """

    def dryrun_time(self):
        self.track.obs.date = self.track.obs.date + (30 * ephem.second)
        self.track.sat.compute(self.track.obs)
        self.nav.azel(self.track.azel())

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


def main(args):
    conf = load_config_file(args.config)
    conf.tle_cache = load_tle_cache(args.tle_cache)

    mock = set(args.mock or [])
    if 'all' in mock:
        mock = {'tx', 'rot', 'con'}

    # Favor command line values over config file values
    conf.txgain = args.tx_gain or conf.txgain
    conf.edl = args.edl_command or conf.edl
    conf.sat_id = args.satellite or conf.sat_id

    if len(conf.edl) <= 10:
        print('Not going to TX because no EDL bytes have been defined')
        mock.add('tx')

    log.basicConfig()
    log.getLogger("apscheduler").setLevel(log.ERROR)

    tracker = Tracker(
        (conf.lat, conf.lon, conf.alt),
        sat_id = conf.sat_id,
        local_only= 'con' in mock,
        tle_cache = conf.tle_cache,
        owmid = conf.owmid,
    )
    rotator = Rotator(
        conf.rotator,
        az_cal = conf.az_cal,
        el_cal = conf.el_cal,
        local_only ='con' in mock,
        no_rot = 'rot' in mock,
    )
    radio = Radio(conf.radio, local_only='con' in mock)
    station = Station(conf.station, no_tx='tx' in mock)
    scheduler = BackgroundScheduler()

    commander = Main(tracker, rotator, radio, station, scheduler)
    if args.action == 'run':
        commander.autorun(
            tx_gain=conf.txgain,
            count=args.pass_count,
            packet=conf.edl,
            no_tx='tx' in mock,
            local_only='con' in mock)
    elif args.action == 'dryrun':
        commander.dryrun()
    elif args.action == 'doppler':
        commander.test_doppler()
    elif args.action == 'nextpass':
        commander.track.sleep_until_next_pass()
    else:
        print(f"Unknown action: {args.action}")
