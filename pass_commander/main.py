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

#  Todo:
#    - verify doppler
#    - add a mode for decoding arbitrary sats, then test

import argparse
import logging as log
import socket
import traceback
from ipaddress import IPv4Address
from math import degrees as deg
from threading import Thread
from time import sleep

import ephem
import pydbus
from apscheduler.schedulers.background import BackgroundScheduler

from . import config, mock
from .Navigator import Navigator
from .Radio import Radio
from .Rotator import Rotator
from .Station import Station
from .Tracker import Tracker


class Main:
    def __init__(
        self,
        tracker: Tracker,
        rotator: Rotator,
        radio: Radio,
        station: Station,
    ):
        self.track = tracker
        self.rot = rotator
        self.rad = radio
        self.sta = station
        self.scheduler = BackgroundScheduler()
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
        self.rad.set_tx_frequency(self.track.freshen())
        self.rad.edl(packet)

    def autorun(self, tx_gain, count=9999, edl_port=10025, no_tx=False, local_only=False):
        print(f"Running for {count} passes")
        while count > 0:
            self.require_clock_sync()
            np = self.track.sleep_until_next_pass()
            self.nav = Navigator(self.track, *np)
            self.work_pass(tx_gain, edl_port, no_tx, local_only)
            seconds = (np[4] - ephem.now()) / ephem.second + 1
            if seconds > 0:
                print(f"Sleeping {seconds:.3f} seconds until pass is really over.")
                sleep(seconds)
            count -= 1

    def work_pass(self, tx_gain, edl_port, no_tx, local_only):
        if local_only:
            return self.test_bg_rotator()
        degc = self.sta.gettemp()
        if degc > 30:
            print(f"Temperature is too high ({degc}°C). Skipping this pass.")
            sleep(1)
            return
        self.track.calibrate()
        print("Adjusted for temp/pressure")
        self.update_rotator()
        print("Started rotator movement")
        sleep(2)
        self.scheduler.add_job(self.update_rotator, "interval", seconds=0.5)
        print("Scheduled rotator")
        self.rad.set_tx_selector("edl")
        print("Selected EDL TX")
        self.rad.set_tx_gain(tx_gain)
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
        if not no_tx:
            source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            source.bind(("", edl_port))
            source.settimeout(0.5)
        print("EDL socket open")
        self.sta.ptt_on()
        print("Station PTT on")
        while self.track.share["target_el"] >= 10:
            if no_tx:
                sleep(0.5)
                continue
            try:
                packet = source.recv(4096)
            except socket.timeout:
                continue
            self.edl(packet)
            print("Sent EDL")
        self.scheduler.remove_all_jobs()
        print("Removed scheduler jobs")
        source.close()
        print("EDL socket closed")
        self.rad.ident()
        print("Sent Morse ident")
        self.sta.ptt_off()
        print("Station PTT off")
        self.rad.set_tx_gain(3)
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
        self.rad.set_rx_frequency(self.track)

    # Testing stuff goes below here

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
            rxfinal = self.rad.rx_frequency(self.track.freshen())
            txfinal = self.rad.tx_frequency(self.track)
            print(f"RX = {rxfinal:.3f}  TX = {txfinal:.3f}")
            sleep(0.1)

    def test_morse(self):
        while True:
            self.rad.ident()
            sleep(30)


def start(action: str, conf: config.Config) -> None:
    log.basicConfig()
    log.getLogger("apscheduler").setLevel(log.ERROR)

    tracker = Tracker(
        (conf.lat, conf.lon, conf.alt),
        sat_id=conf.sat_id,
        local_only='con' in conf.mock,
        tle_cache=conf.tle_cache,
        owmid=conf.owmid,
    )
    rotator = Rotator(
        str(conf.rotator),
        az_cal=conf.az_cal,
        el_cal=conf.el_cal,
        local_only='con' in conf.mock,
        no_rot='rot' in conf.mock,
    )
    radio = Radio(str(conf.radio))
    station = Station(str(conf.station))

    commander = Main(tracker, rotator, radio, station)
    if action == 'run':
        commander.autorun(
            tx_gain=conf.txgain,
            count=conf.pass_count,
            edl_port=conf.edl_port,
            no_tx='tx' in conf.mock,
            local_only='con' in conf.mock,
        )
    elif action == 'dryrun':
        commander.dryrun()
    elif action == 'doppler':
        commander.test_doppler()
    elif action == 'nextpass':
        commander.track.sleep_until_next_pass()
    else:
        print(f"Unknown action: {action}")


def cfgerr(args: argparse.Namespace, msg: str) -> None:
    if args.verbose:
        traceback.print_exc()
        print()
    print(f"In '{args.config}'", msg)


def main(args: argparse.Namespace) -> None:
    if args.config.is_dir():
        args.config /= "pass_commander.toml"

    if args.template:
        try:
            config.Config.template(args.config)
        except FileExistsError:
            cfgerr(args, 'delete existing file before creating template')
        else:
            print(f"Config template generated at '{args.config}'")
            print(f"Edit '{args.config}' <template text> before running again")
        return

    try:
        conf = config.Config(args.config)
    except config.ConfigNotFoundError as e:
        cfgerr(
            args,
            f"the file is missing ({type(e.__cause__).__name__}). Initialize using --template",
        )
    except config.InvalidTomlError as e:
        cfgerr(args, f"there is invalid toml: {e}\nPossibly an unquoted string?")
    except config.MissingKeyError as e:
        cfgerr(args, f"required key '{e.table}.{e.key}' is missing")
    except config.TemplateTextError as e:
        cfgerr(args, f"key '{e}' still has template text. Replace <angle brackets>")
    except config.UnknownKeyError as e:
        cfgerr(args, f"remove unknown keys: {' '.join(e.keys)}")
    except config.KeyValidationError as e:
        cfgerr(args, f"key '{e.table}.{e.key}' has invalid type {e.actual}, expected {e.expect}")
    except config.IpValidationError as e:
        cfgerr(args, f"contents of '{e.table}.{e.key}' is not a valid IP")
    except config.TleValidationError as e:
        cfgerr(args, f"TLE '{e.name}' is invalid: {e.__cause__}")
    else:
        conf.mock = set(args.mock or [])
        if 'all' in conf.mock:
            conf.mock = {'tx', 'rot', 'con'}
        # Favor command line values over config file values
        conf.txgain = args.tx_gain or conf.txgain
        conf.sat_id = args.satellite or conf.sat_id
        if not conf.sat_id:
            print("No satellite specified. Set on command line (see --help) or in config file.")
            return
        conf.pass_count = args.pass_count
        if 'con' in conf.mock:
            conf.radio = IPv4Address("127.0.0.2")
            mock.Edl(str(conf.radio), 10025).start()
            flowgraph = mock.Flowgraph(str(conf.radio), 10080)
            Thread(target=flowgraph.start, daemon=True).start()

        if 'tx' in conf.mock:
            conf.station = IPv4Address("127.0.0.2")
            mock.Stationd(str(conf.station), 5005)

        start(args.action, conf)
