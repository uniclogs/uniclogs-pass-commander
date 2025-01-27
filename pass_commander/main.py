import logging
import socket
from argparse import ArgumentParser, Namespace, RawTextHelpFormatter
from ipaddress import IPv4Address
from math import degrees as deg
from pathlib import Path
from textwrap import dedent
from threading import Thread
from time import sleep

import ephem
from apscheduler.schedulers.background import BackgroundScheduler
from jeepney import DBusAddress, Properties
from jeepney.io.blocking import open_dbus_connection

from . import config, mock
from .navigator import Navigator
from .radio import Radio
from .rotator import Rotator
from .station import Station
from .tracker import Tracker

logger = logging.getLogger(__name__)


class Main:
    def __init__(self, conf: config.Config) -> None:
        '''Create the main pass coordinator.'''
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()

        self.min_el = ephem.degrees(10.0)
        self.track = Tracker(
            (conf.lat, conf.lon, conf.alt),
            sat_id=conf.sat_id,
            local_only='con' in conf.mock,
            tle_cache=conf.tle_cache,
            owmid=conf.owmid,
        )
        self.rot = Rotator(None if 'con' in conf.mock else str(conf.rotator), cal=conf.cal)
        self.rad = Radio(str(conf.radio), conf.radio_xmlrpc, conf.radio_edl, conf.name)
        self.sta = Station(str(conf.station))
        self.uhf = Station(str(conf.station), band='uhf')

        self.max_temp = 30.0

    def ntp_synchronized(self) -> bool:
        # FIXME: Paraphrased from man org.freedesktop.timedate1:
        # NTPSynchronized shows whether the kernel reports the time as
        # synchronized, reported by the system call adjtimex(3). The purpose of
        # this D-Bus property is to allow remote clients to access this
        # information. Local clients can access the information directly.
        #
        # I'd prefer to not use D-Bus but I can't find any existing Python
        # bindings for adjtimex() and the struct argument is sufficiently
        # complicated that I don't really want to write my own ctypes binding.
        msg = Properties(
            DBusAddress(
                object_path='/org/freedesktop/timedate1',
                bus_name='org.freedesktop.timedate1',
                interface='org.freedesktop.timedate1',
            )
        ).get("NTPSynchronized")
        with open_dbus_connection(bus='SYSTEM') as con:
            return bool(con.send_and_get_reply(msg).body[0][1])

    def require_clock_sync(self) -> None:
        while not self.ntp_synchronized():
            logger.warning("System clock is not synchronized. Sleeping 60 seconds.")
            sleep(60)
        logger.info("System clock is synchronized.")

    def edl(self, packet: bytes, offset: ephem.Date) -> None:
        self.rad.set_tx_frequency(self.track.freshen(ephem.Date(self.track.now() + offset)))
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

    def work_pass(self, tx_gain: int, edl_port: int, offset: ephem.Date) -> None:  # noqa: PLR0915
        degc = self.sta.gettemp()
        if degc > self.max_temp:
            logger.info(
                "Temperature is too high (%f°C > %f°C). Skipping this pass.", degc, self.max_temp
            )
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
        self.uhf.lna_on()
        self.sta.pa_on()
        self.sta.ptt_on()
        self.rad.ident()
        logger.info("Sent Morse ident")
        self.sta.ptt_off()
        logger.info("Waiting for bird to reach %d°el", self.min_el)
        while deg(self.track.azel().el) < self.min_el:
            sleep(0.1)
        logger.info("Bird above %d°el", self.min_el)
        source = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        source.bind(("", edl_port))
        source.settimeout(0.5)
        logger.info("EDL socket open")
        self.sta.ptt_on()
        while deg(self.track.azel().el) >= self.min_el:
            try:
                packet = source.recv(4096)
            except TimeoutError:
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
        self.uhf.lna_on()
        self.rad.set_tx_gain(3)
        logger.info("Set TX gain to min")
        self.rot.park()
        logger.info("Parked rotator")
        logger.info("Waiting for PA to cool")
        sleep(120)
        self.sta.pa_off()

    def update_rotator(self, offset: ephem.Date) -> None:
        if self.nav is None:
            raise ValueError("self.nav was not initialized")
        azel = self.nav.azel(self.track.freshen(ephem.Date(self.track.now() + offset)).azel())
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
            self.update_rotator(0)
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


def handle_args() -> Namespace:  # noqa: D103
    parser = ArgumentParser(formatter_class=RawTextHelpFormatter)
    parser.add_argument(
        "-a",
        "--action",
        choices=("run", "dryrun", "doppler", "nextpass"),
        help=dedent(
            """\
            Which action to have Pass Commander take
            - run: Normal operation
            - dryrun: Simulate the next pass immediately
            - doppler: Show present RX/TX frequencies
            - nextpass: Sleep until next pass and then quit
            Default: '%(default)s'"""
        ),
        default="run",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="~/.config/OreSat/pass_commander.toml",
        type=Path,
        help=dedent(
            """\
            Path to .toml config file. If dir will assume 'pass_commander.toml' in that dir
            Default: '%(default)s'"""
        ),
    )
    parser.add_argument(
        "--template",
        action="store_true",
        help="Generate a config template at the path specified by --config",
    )
    parser.add_argument(
        "-e",
        "--edl-port",
        type=int,
        default=10025,
        help="Port to listen for EDL packets on, default: %(default)s",
    )
    parser.add_argument(
        "-m",
        "--mock",
        action="append",
        choices=("tx", "rot", "con", "all"),
        help=dedent(
            """\
            Use a simulated (mocked) external dependency, not the real thing
            - tx: No PTT or EDL bytes sent to flowgraph
            - rot: No actual movement commanded for the rotator
            - con: Don't use network services - TLEs, weather, rot2prog, stationd
            - all: All of the above
            Can be issued multiple times, e.g. '-m tx -m rot' will disable tx and rotator"""
        ),
    )
    parser.add_argument(
        "-p",
        "--pass-count",
        type=int,
        default=9999,
        help="Maximum number of passes to operate before shutting down. Default: '%(default)s'",
    )
    parser.add_argument(
        "-s",
        "--satellite",
        help=dedent(
            """\
            Can be International Designator, Catalog Number, or Name.
            If `--mock con` is specified will search local TLE cache and Gpredict cache
            """
        ),
    )
    parser.add_argument(
        "-t", "--tx-gain", type=int, help="Transmit gain, usually between 0 and 100ish"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="Output additional debugging information",
    )
    return parser.parse_args()


def _cfgerr(args: Namespace, msg: str) -> None:
    logger.debug("Config error", exc_info=True)
    logger.error("In '%s': %s", args.config, msg)


def main() -> None:  # noqa: D103 C901 PLR0912 PLR0915
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.ERROR)

    args = handle_args()
    if args.config.is_dir():
        args.config /= "pass_commander.toml"

    if args.template:
        try:
            config.Config.template(args.config)
        except FileExistsError:
            _cfgerr(args, 'delete existing file before creating template')
        else:
            logger.info("Config template generated at '%s'", args.config)
            logger.info("Edit '%s' <template text> before running again", args.config)
        return

    try:
        conf = config.Config(args.config)
    except config.ConfigNotFoundError as e:
        _cfgerr(
            args,
            f"the file is missing ({type(e.__cause__).__name__}). Initialize using --template",
        )
    except config.InvalidTomlError as e:
        _cfgerr(args, f"there is invalid toml: {e}\nPossibly an unquoted string?")
    except config.MissingKeyError as e:
        _cfgerr(args, f"required key '{e.table}.{e.key}' is missing")
    except config.TemplateTextError as e:
        _cfgerr(args, f"key '{e}' still has template text. Replace <angle brackets>")
    except config.UnknownKeyError as e:
        _cfgerr(args, f"remove unknown keys: {' '.join(e.keys)}")
    except config.KeyValidationError as e:
        _cfgerr(args, f"key '{e.table}.{e.key}' has invalid type {e.actual}, expected {e.expect}")
    except config.IpValidationError as e:
        _cfgerr(args, f"contents of '{e.table}.{e.key}' is not a valid IP")
    except config.TleValidationError as e:
        _cfgerr(args, f"TLE '{e.name}' is invalid: {e.__cause__}")
    else:
        conf.mock = set(args.mock or [])
        if 'all' in conf.mock:
            conf.mock = {'tx', 'rot', 'con'}
        # Favor command line values over config file values
        conf.txgain = args.tx_gain or conf.txgain
        conf.sat_id = args.satellite or conf.sat_id
        if not conf.sat_id:
            logger.error(
                "No satellite specified. Set on command line (see --help) or in config file."
            )
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

        commander = Main(conf)

        if args.action == 'run':
            commander.autorun(
                tx_gain=conf.txgain,
                count=conf.pass_count,
                edl_port=conf.edl_port,
            )
        elif args.action == 'dryrun':
            commander.dryrun()
        elif args.action == 'doppler':
            commander.test_doppler()
        elif args.action == 'nextpass':
            commander.track.sleep_until_next_pass()
        else:
            logger.info("Unknown action: %s", args.action)
