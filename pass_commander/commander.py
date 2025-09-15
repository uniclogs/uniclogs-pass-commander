import logging
import select
import socket
from datetime import timedelta
from functools import partial
from inspect import signature
from math import atan2, tau
from time import sleep

import linuxfd
import numpy as np
from jeepney import DBusAddress, Properties
from jeepney.io.blocking import open_dbus_connection
from skyfield.api import Time, load
from skyfield.toposlib import GeographicPosition
from skyfield.units import Angle, Velocity

from .config import AzEl, Config
from .radio import Radio
from .rotator import Rotator
from .satellite import Satellite
from .station import Station
from .tracker import PassInfo, Tracker

logger = logging.getLogger(__name__)


class SinglePass:
    def __init__(
        self,
        conf: Config,
        lna_delay: float | None = None,
        morse_delay: float | None = None,
        cooloff_delay: float | None = None,
    ) -> None:
        '''Assemble all things needed to run a single pass.'''
        # FIXME fetch these values from stationd/gnuradio
        if lna_delay is None:
            lna_delay = signature(Station.__init__).parameters['lna_delay'].default
        if morse_delay is None:
            morse_delay = signature(Radio.__init__).parameters['morse_delay'].default
        if cooloff_delay is None:
            cooloff_delay = 120.0
        self.conf = conf
        # TODO: check if resources are available but don't require until start of pass
        self.sta = Station(conf.station, band='l-band')
        self.uhf = Station(conf.station, band='uhf', lna_delay=lna_delay)
        self.rot = Rotator(conf.rotator, cal=conf.cal)
        self.rad = Radio(conf.flowgraph, conf.edl_dest, conf.name, morse_delay=morse_delay)
        self.ts = load.timescale()

        self.cooloff_delay = cooloff_delay
        self.min_el = 15  # FIXME: move to calc

    def work(
        self,
        pos: tuple[Time, Angle, Angle],
        nav: tuple[Time, Angle, Angle],
        rv: tuple[Time, Velocity],
    ) -> None:
        '''Do all actions for a single pass.

        Parameters
        ----------
        pos
            Position of the satellite, given in (time, azimuth, elevation)
        nav
            Navigation positions for the antenna, given in (time, azimuth, elevation). The rotator
            may be using an alternate track mode (e.g. flip, backhand) so az and el aren't always
            going to be the same as pos. Also it may have different times. El can go from 0 - 180.
        rv
            Range velocity of the satellite, as in how fast it's approaching or receding from the
            observer, given in (time, velocity). Used for doppler shift calculations.

        '''
        # Tasks:
        # - Pre-position antenna
        # - configure gain/radios
        # - start rx doppler
        # - at 0 degrees - send morse
        # - at min_el degrees - enable edl
        # - ability to mark maxel
        # - at min_el degrees - disable edl
        # - at 0 degrees - send morse
        # - park antenna
        # - disable gain/radios

        # calculate events array for each task?
        self.epoll = select.epoll()
        self.epoll.register(self.rot.listener, select.EPOLLIN)
        aosfd = linuxfd.timerfd(rtc=True, nonBlocking=True)
        losfd = linuxfd.timerfd(rtc=True, nonBlocking=True)
        rotfd = linuxfd.timerfd(rtc=True, nonBlocking=True)
        radfd = linuxfd.timerfd(rtc=True, nonBlocking=True)
        posfd = linuxfd.timerfd(rtc=True, nonBlocking=True)
        thmfd = linuxfd.timerfd(rtc=True, nonBlocking=True)

        # FIXME: log messages at AOS, Max el, LOS
        times, az, el = pos
        # first time above min_el
        aos = times[np.argmax(el.degrees > self.min_el)]
        # last time above min_el
        los = times[len(el.degrees) - 1 - np.argmax(np.flip(el.degrees) > self.min_el)]

        logger.info("AOS: %s", aos.utc_datetime())
        logger.info("LOS: %s", los.utc_datetime())

        self.action = {
            aosfd.fileno(): partial(self.on_rise, aosfd),
            losfd.fileno(): partial(self.on_fall, losfd),
            rotfd.fileno(): partial(
                self.on_rotator, rotfd, (iter(nav[0]), iter(nav[1].degrees), iter(nav[2].degrees))
            ),
            radfd.fileno(): partial(self.on_rx_doppler, radfd, (iter(rv[0]), iter(rv[1].m_per_s))),
            posfd.fileno(): partial(
                self.on_pos, posfd, (iter(times), iter(az.degrees), iter(el.degrees))
            ),
            thmfd.fileno(): partial(self.on_thermal, thmfd),
        }

        self.edl: socket.socket | None = None

        # Orient antenna to where the satellite wil rise
        # FIXME: compensate for slew rate, point at midpointish thing
        try:
            self.pre_position(nav[1].degrees[0], nav[2].degrees[0])

            self.epoll.register(aosfd.fileno(), select.EPOLLIN)
            self.epoll.register(losfd.fileno(), select.EPOLLIN)
            self.epoll.register(rotfd.fileno(), select.EPOLLIN)
            self.epoll.register(radfd.fileno(), select.EPOLLIN)
            self.epoll.register(posfd.fileno(), select.EPOLLIN)
            self.epoll.register(thmfd.fileno(), select.EPOLLIN)

            aosfd.settime(aos.utc_datetime().timestamp(), absolute=True)
            losfd.settime(los.utc_datetime().timestamp(), absolute=True)
            rotfd.settime(nav[0][0].utc_datetime().timestamp(), absolute=True)
            radfd.settime(rv[0][0].utc_datetime().timestamp(), absolute=True)
            posfd.settime(pos[0][0].utc_datetime().timestamp(), absolute=True)
            thmfd.settime(self.ts.now().utc_datetime().timestamp(), absolute=True)

            stop = False
            while not stop:
                for fd, event in self.epoll.poll(-1):
                    try:
                        logger.debug("%s", self.action[fd])
                        if stop := not self.action[fd](event):
                            break
                    except StopIteration:
                        self.epoll.unregister(fd)
        except Exception:
            # It'll take a while to get through the finally block so notify the user early on error
            logger.exception("!!Work pass interrupted:")
            raise
        finally:
            self.reset_hardware()

    def reset_hardware(self) -> None:
        logger.info("Pass ending, safing hardware")
        self.sta.ptt_off()
        if self.edl is not None:
            self.edl.close()
        self.uhf.lna_off()
        self.rad.set_tx_gain(3)

        self.rot.park()
        logger.info("Parked rotator")
        logger.info("Waiting %ds for PA to cool", self.cooloff_delay)
        sleep(self.cooloff_delay)
        self.sta.pa_off()

    def ident(self) -> bool:
        # The identifier must be sent
        # - Within 10 minutes of operating
        # - Every 10 minutes after that
        # - At the end of operating

        logger.info("Sending morse identifier")
        self.sta.ptt_on()
        try:
            self.rad.ident()
        finally:
            self.sta.ptt_off()
        logger.info("Morse identifier sent")
        return True

    def pre_position(self, az: float, el: float) -> None:
        self.rot.go(AzEl(az, el))
        logger.info("Started rotator movement")
        self.rot.start_polling(AzEl(az, el))
        # FIXME: guess from slew rate about how long it would take instead of
        # waiting indefinitely. We'll need some way of finding slew rate first
        # though.
        events = self.epoll.poll(-1)
        if len(events) > 1:
            raise RuntimeError("More events than expected")
        if events[0][0] != self.rot.listener:
            raise RuntimeError("Unexpected event fired")
        self.epoll.unregister(self.rot.listener)
        pos = self.rot.event()  # clears the event
        logger.info("pre-position arrived at %s", pos)
        self.on_positioned(events[0][1])

    def on_positioned(self, _event: int) -> bool:
        logger.info("Rotator at initial position, enabling pa, lna")
        self.rad.set_tx_gain(self.conf.txgain)
        self.uhf.lna_on()
        self.sta.pa_on()
        self.ident()
        logger.info("Initial position tasks complete")
        return True

    def on_rotator(
        self, timer: linuxfd.timerfd, nav: tuple[Time, Angle, Angle], _event: int
    ) -> bool:
        timer.read()
        time, az, el = next(nav[0]), next(nav[1]), next(nav[2])
        while time < self.ts.now():
            logger.info(
                '%-28s%s %7.3f°az %7.3f°el',
                'Skipping nav',
                time.utc_datetime(),
                az,
                el,
            )
            time, az, el = next(nav[0]), next(nav[1]), next(nav[2])
        timer.settime(time.utc_datetime().timestamp(), absolute=True)
        self.rot.go(AzEl(az, el))
        return True

    def on_pos(self, timer: linuxfd.timerfd, pos: tuple[Time, Angle, Angle], _event: int) -> bool:
        timer.read()
        time, az, el = next(pos[0]), next(pos[1]), next(pos[2])
        logger.info('%-28s: %7.3f°az %7.3f°el', "Satellite position", az, el)
        timer.settime(time.utc_datetime().timestamp(), absolute=True)
        return True

    def on_rise(self, timer: linuxfd.timerfd, _event: int) -> bool:
        logger.info("AOS %s", timer.read())
        self.rad.set_tx_selector("edl")
        self.sta.ptt_on()

        self.edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        self.edl.bind(self.conf.edl)
        logger.info("EDL socket open")
        self.epoll.register(self.edl.fileno(), select.EPOLLIN | select.EPOLLERR)
        self.action[self.edl.fileno()] = partial(self.on_edl, self.edl)
        return True

    # FIXME: setup on_fall in on_rise so that self.edl can be local
    def on_fall(self, timer: linuxfd.timerfd, _event: int) -> bool:
        logger.info("LOS %s", timer.read())
        if self.edl is not None:
            self.edl.close()
        self.edl = None
        logger.info("EDL socket closed")
        self.ident()
        self.sta.ptt_off()
        return False

    def on_edl(self, edl: socket.socket, _event: int) -> bool:
        packet = edl.recv(4096)
        # FIXME: Recalculate current range_vel for exact time?
        self.rad.edl(packet, self.current_rv)
        logger.info("Sent EDL")
        return True

    def on_rx_doppler(self, timer: linuxfd.timerfd, rv: Velocity, _event: int) -> bool:
        timer.read()
        time, range_velocity = next(rv[0]), next(rv[1])
        while time < self.ts.now():
            logger.info(
                '%-28s%s %7.3f rv',
                'Skipping doppler',
                time.utc_datetime(),
                range_velocity,
            )
            time, range_velocity = next(rv[0]), next(rv[1])

        timer.settime(time.utc_datetime().timestamp(), absolute=True)
        # FIXME: set doppler to point that minimizes error over the interval (midpoint?)
        self.current_rv = range_velocity
        logger.debug("doppler %f", self.current_rv)
        self.rad.set_rx_frequency(self.current_rv)
        return True

    def on_thermal(self, timer: linuxfd.timerfd, _event: int) -> bool:
        timer.read()

        degc = self.sta.gettemp()
        if degc > self.conf.temp_limit:
            logger.info(
                "Temperature is too high (%.1f°C > %.1f°C). Skipping this pass.",
                degc,
                self.conf.temp_limit,
            )
            raise RuntimeError("Temperature too high")
        timer.settime(self.ts.now().utc_datetime().timestamp() + 30, absolute=True)
        return True


class Commander:
    def __init__(self, conf: Config) -> None:
        '''Create the main pass coordinator.'''
        self.conf = conf
        self.track = Tracker(conf.observer, owmid=conf.owmid)
        self.singlepass = SinglePass(conf)

    def require_clock_sync(self) -> None:
        def ntp_synchronized() -> bool:
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

        while not ntp_synchronized():
            logger.warning("System clock is not synchronized. Sleeping 60 seconds.")
            sleep(60)
        logger.info("System clock is synchronized.")

    def sleep_until_next_pass(self) -> tuple[Satellite, PassInfo]:
        # FIXME: How many days is a TLE good for? Set next_pass(lookahead) based on that
        # FIXME: How often are TLEs updated? Set tle_refresh based on that
        # FIXME: Now that we have an event loop can this be part of it?

        while True:
            sat = Satellite(
                self.conf.sat_id, tle_cache=self.conf.tle_cache, local_only='con' in self.conf.mock
            )
            np = self.track.next_pass(sat, min_el=self.conf.min_el)
            if np is None:
                # FIXME: sleep until next TLE?
                raise RuntimeError("No pass found")

            to_sleep = timedelta(days=np.rise.time - self.track.ts.now())
            if to_sleep <= timedelta():
                logger.info("In a pass now!")
                return sat, np

            logger.info(
                "Sleeping %s until next rise time %s for a %.2f°el pass.",
                to_sleep,
                np.rise.time.astimezone(None),
                np.culm[0].el.degrees,
            )

            tle_refresh = timedelta(days=1)
            # FIXME: wake up a bit before a pass to adjust TLEs?
            sleep(min(to_sleep.total_seconds(), tle_refresh.total_seconds()))

            tle_age = timedelta(days=self.track.ts.now() - sat.epoch)
            if tle_age <= tle_refresh:
                return sat, np
            logger.info('TLE out of date by %s, refreshing', tle_age)

        raise RuntimeError("Unreachable?")

    def autorun(self, count: int) -> None:
        logger.info("Running for %d passes", count)
        while count > 0:
            self.require_clock_sync()
            sat, np = self.sleep_until_next_pass()

            # Pre-compute pass time/alt/az/rv
            temp, pressure = self.track.weather()
            logger.info("Current weather: %f°C %f mBar", temp, pressure)

            pos, rv = self.track.track(sat, np, temp, pressure)
            nav = self.singlepass.rot.path(np, pos)
            self.singlepass.work(pos, nav, rv)

            seconds = timedelta(days=np.fall.time - self.track.ts.now()).total_seconds()
            if seconds > 0:
                logger.info("Sleeping %.3f seconds until pass is really over.", seconds)
                sleep(seconds)
            count -= 1

    # Testing stuff goes below here

    def point(self, coord: GeographicPosition) -> None:
        # The real proper way of doing heading on a sphere involves the haversine formula but I
        # don't really want to implement it myself and also pull in a library just for this. Using
        # arctan assumes a flat plane but I claim (without having done any math whatsoever) that
        # this is sufficient since we're not intending to point at points past the horizon and also
        # not use this in the arctic circle.
        # FIXME: before we deploy a uniclogs station in Svalbard (one day I promise)
        n = coord.latitude.radians - self.conf.observer.latitude.radians
        e = coord.longitude.radians - self.conf.observer.longitude.radians
        # For trig functions like atan2 we treat N as x and E as y. It also outputs in the -180 -
        # 180 range but we want 0 - 360.
        az = atan2(e, n) % tau

        # A simulated pointing pass is two points, one at now with the appropriate azimuth, and one
        # forever far in the future that won't ever reasonably be reached.
        now = self.track.ts.now()
        # Python can't represent dates more than 10,000 years in the future and timerfds don't do
        # 10,000 days(?) so 1,000 days is now forever.
        times = self.track.ts.linspace(now, now + 1000, 2)
        pos = (times, Angle(radians=[az, az]), Angle(degrees=[0, 0]))
        nav = (times, Angle(radians=[az, az]), Angle(degrees=[0, 0]))
        rv = (times, Velocity.m_per_s([0, 0]))

        self.singlepass.work(pos, nav, rv)

    def dryrun(self) -> None:
        sat = Satellite(
            self.conf.sat_id, tle_cache=self.conf.tle_cache, local_only='con' in self.conf.mock
        )
        np = self.track.next_pass(sat, min_el=Angle(degrees=80), lookahead=timedelta(days=30))
        if np is None:
            raise RuntimeError("No pass found")
        logger.info(
            "Rise time: %s Max el: %.3f", np.rise.time.utc_datetime(), np.culm[0].el.degrees
        )
        (postime, az, el), (rvtime, rangevel) = self.track.track(sat, np)
        navtime, navaz, navel = self.singlepass.rot.path(np, (postime, az, el))
        offset = postime[0] - self.track.ts.now()
        logger.info("Dryrun offset: %f", offset)
        self.singlepass.work(
            (postime - offset, az, el),
            (navtime - offset, navaz, navel),
            (rvtime - offset, rangevel),
        )
        logger.info("Dry run complete")

    def test_morse(self) -> None:
        while True:
            self.singlepass.ident()
            sleep(30)
