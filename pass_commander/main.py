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
import logging
import socket
import traceback
from ipaddress import IPv4Address
from math import degrees as deg
from threading import Thread
from time import sleep
from typing import Optional

import ephem
import pydbus
from apscheduler.schedulers.background import BackgroundScheduler

from . import config, mock
from .Navigator import Navigator
from .Radio import Radio
from .Rotator import Rotator
from .Station import Station
from .Tracker import Tracker

logger = logging.getLogger(__name__)


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
        self.nav: Optional[Navigator] = None

    def NTPSynchronized(self) -> bool:
        return bool(pydbus.SystemBus().get(".timedate1").NTPSynchronized)

    def require_clock_sync(self) -> None:
        while not self.NTPSynchronized():
            logger.warning("System clock is not synchronized. Sleeping 60 seconds.")
            sleep(60)
        logger.info("System clock is synchronized.")

    def edl(self, packet: bytes, offset: ephem.Date) -> None:
        self.rad.set_tx_frequency(self.track.freshen(ephem.Date(ephem.now() + offset)))
        self.rad.edl(packet)

    def autorun(self, tx_gain: int, count: int, edl_port: int) -> None:
        logger.info("Running for %d passes", count)
        while count > 0:
            self.require_clock_sync()
            np = self.track.sleep_until_next_pass()
            self.nav = Navigator(np)
            self.work_pass(tx_gain, edl_port, ephem.Date(0))
            seconds = (np.set_time - ephem.now()) / ephem.second + 1
            if seconds > 0:
                logger.info("Sleeping %.3f seconds until pass is really over.", seconds)
                sleep(seconds)
            count -= 1

    def work_pass(self, tx_gain: int, edl_port: int, offset: ephem.Date) -> None:
        degc = self.sta.gettemp()
        if degc > 30:
            logger.info("Temperature is too high (%f°C). Skipping this pass.", degc)
            sleep(1)
            return
        self.track.calibrate()
        logger.info("Adjusted for temp/pressure")
        self.update_rotator(offset)
        logger.info("Started rotator movement")
        sleep(2)
        self.scheduler.add_job(self.update_rotator, "interval", seconds=0.5, args=[offset])
        logger.info("Scheduled rotator")
        self.rad.set_tx_selector("edl")
        logger.info("Selected EDL TX")
        self.rad.set_tx_gain(tx_gain)
        logger.info("Set TX gain")
        sleep(2)
        logger.info("Rotator should be moving by now")
        while self.rot.is_moving:
            sleep(0.1)
        if self.rot.is_moving:
            logger.error("Rotator communication anomaly detected. Skipping this pass.")
            self.scheduler.remove_all_jobs()
            sleep(1)
            return
        logger.info("Stopped moving")
        self.sta.pa_on()
        logger.info("Station amps on")
        sleep(0.2)
        self.sta.ptt_on()
        logger.info("Station PTT on")
        self.rad.ident()
        logger.info("Sent Morse ident")
        self.sta.ptt_off()
        logger.info("Station PTT off")
        logger.info("Waiting for bird to reach 10°el")
        while deg(self.track.azel().el) < 10:
            sleep(0.1)
        logger.info("Bird above 10°el")
        source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        source.bind(("", edl_port))
        source.settimeout(0.5)
        logger.info("EDL socket open")
        self.sta.ptt_on()
        logger.info("Station PTT on")
        while deg(self.track.azel().el) >= 10:
            try:
                packet = source.recv(4096)
            except socket.timeout:
                continue
            self.edl(packet, offset)
            logger.info("Sent EDL")
        self.scheduler.remove_all_jobs()
        logger.info("Removed scheduler jobs")
        source.close()
        logger.info("EDL socket closed")
        self.rad.ident()
        logger.info("Sent Morse ident")
        self.sta.ptt_off()
        logger.info("Station PTT off")
        self.rad.set_tx_gain(3)
        logger.info("Set TX gain to min")
        self.rot.park()
        logger.info("Parked rotator")
        logger.info("Waiting for PA to cool")
        sleep(120)
        self.sta.pa_off()
        logger.info("Station shutdown TX amp")

    def update_rotator(self, offset: ephem.Date) -> None:
        assert self.nav is not None
        azel = self.nav.azel(self.track.freshen(ephem.Date(ephem.now() + offset)).azel())
        self.rot.go(config.AzEl(*(deg(x) for x in azel)))
        self.rad.set_rx_frequency(self.track)

    # Testing stuff goes below here

    def dryrun(self) -> None:
        np = self.track.get_next_pass(80)
        self.nav = Navigator(np)
        self.track.obs.date = np.rise_time
        self.work_pass(tx_gain=3, edl_port=10025, offset=np.rise_time - ephem.now())

    def test_rotator(self) -> None:
        while True:
            self.update_rotator()
            sleep(0.1)

    def test_bg_rotator(self) -> None:
        self.scheduler.add_job(self.update_rotator, "interval", seconds=0.5)
        while True:
            sleep(1000)

    def test_doppler(self) -> None:
        while True:
            rxfinal = self.rad.rx_frequency(self.track.freshen())
            txfinal = self.rad.tx_frequency(self.track)
            logger.info("RX = %.3f  TX = %.3f", rxfinal, txfinal)
            sleep(0.1)

    def test_morse(self) -> None:
        while True:
            self.rad.ident()
            sleep(30)


def start(action: str, conf: config.Config) -> None:
    tracker = Tracker(
        (conf.lat, conf.lon, conf.alt),
        sat_id=conf.sat_id,
        local_only='con' in conf.mock,
        tle_cache=conf.tle_cache,
        owmid=conf.owmid,
    )
    rotator = Rotator(None if 'con' in conf.mock else str(conf.rotator), cal=conf.cal)
    radio = Radio(str(conf.radio), conf.radio_xmlrpc, conf.radio_edl)
    station = Station(str(conf.station))

    commander = Main(tracker, rotator, radio, station)
    if action == 'run':
        commander.autorun(
            tx_gain=conf.txgain,
            count=conf.pass_count,
            edl_port=conf.edl_port,
        )
    elif action == 'dryrun':
        commander.dryrun()
    elif action == 'doppler':
        commander.test_doppler()
    elif action == 'nextpass':
        commander.track.sleep_until_next_pass()
    else:
        logger.info("Unknown action: %s", action)


def cfgerr(args: argparse.Namespace, msg: str) -> None:
    if args.verbose:
        traceback.print_exc()
        print()
    print(f"In '{args.config}'", msg)


def main(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.ERROR)

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
            # Radio mock
            conf.radio = IPv4Address("127.0.0.2")
            conf.radio_edl = 10125
            mock.Edl(str(conf.radio), conf.radio_edl).start()
            flowgraph = mock.Flowgraph(str(conf.radio), 10080)
            Thread(target=flowgraph.start, daemon=True).start()
            # Tracker mock
            conf.owmid = ''

        if 'tx' in conf.mock:
            conf.station = IPv4Address("127.0.0.2")
            mock.Stationd(str(conf.station), 5005).start()

        start(args.action, conf)
