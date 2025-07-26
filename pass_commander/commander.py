# ruff: noqa: ERA001
import logging
import select
import socket
from datetime import timedelta
from functools import partial
from inspect import signature
from time import sleep

import linuxfd
import numpy as np
from jeepney import DBusAddress, Properties
from jeepney.io.blocking import open_dbus_connection
from skyfield.api import Time
from skyfield.units import Angle, Velocity

from .config import AzEl, Config
from .radio import Radio
from .rotator import Rotator
from .satellite import Satellite
from .station import Station
from .tracker import Tracker

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

        self.cooloff_delay = cooloff_delay
        self.min_el = 15  # FIXME: move to calc

    def work(self, pos: tuple[Time, Angle, Angle], rv: tuple[Time, Velocity]) -> None:
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

        # FIXME: log messages at AOS, Max el, LOS
        times, az, el = pos
        aos = times[np.argmax(el.degrees > self.min_el)]
        los = times[len(el.degrees) - 1 - np.argmax(np.flip(el.degrees) > self.min_el)]

        logger.info("AOS: %s", aos.utc_datetime())
        logger.info("LOS: %s", los.utc_datetime())

        self.action = {
            aosfd.fileno(): partial(self.on_rise, aosfd),
            losfd.fileno(): partial(self.on_fall, losfd),
            self.rot.listener: partial(self.on_rot_event, self.rot),
            rotfd.fileno(): partial(
                self.on_rotator, rotfd, (iter(times), iter(az.degrees), iter(el.degrees))
            ),
            radfd.fileno(): partial(self.on_rx_doppler, radfd, (iter(rv[0]), iter(rv[1].m_per_s))),
        }

        self.edl: socket.socket | None = None

        # FIXME: event when rotator reaches position/error
        # FIXME: skip during pass resume
        # Orient antenna to where the satellite wil rise
        # FIXME: compensate for slew rate, point at midpointish thing
        try:
            self.pre_position(az.degrees[0], el.degrees[0])

            self.epoll.register(aosfd.fileno(), select.EPOLLIN)
            self.epoll.register(losfd.fileno(), select.EPOLLIN)
            self.epoll.register(rotfd.fileno(), select.EPOLLIN)
            self.epoll.register(radfd.fileno(), select.EPOLLIN)

            aosfd.settime(aos.utc_datetime().timestamp(), absolute=True)
            losfd.settime(los.utc_datetime().timestamp(), absolute=True)
            rotfd.settime(times[0].utc_datetime().timestamp(), absolute=True)
            radfd.settime(times[0].utc_datetime().timestamp(), absolute=True)

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
                        logger.exception("Event loop exception")
                        stop = True
        finally:
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
        # FIXME: guess from slew rate about how long it would take instead
        # of waiting indefinitely
        events = self.epoll.poll(-1)
        if len(events) > 1:
            raise RuntimeError("More events than expected")
        if events[0][0] != self.rot.listener:
            raise RuntimeError("Unexpected event fired")
        self.on_positioned(self.rot, events[0][1])

    def on_positioned(self, rot: Rotator, _event: int) -> bool:
        logger.info("Rotator at initial position, enabling pa, lna")
        rot.event()
        self.rad.set_tx_gain(self.conf.txgain)
        self.uhf.lna_on()
        self.sta.pa_on()
        self.ident()
        logger.info("Initial position tasks complete")
        return True

    def on_rotator(
        self, timer: linuxfd.timerfd, pos: tuple[Time, Angle, Angle], _event: int
    ) -> bool:
        timer.read()
        # FIXME: find original track and log it
        # logger.info(
        #    '%-28s%7.3f°az %7.3f°el to %7.3f°az %7.3f°el',
        #    "Navigation corrected from",
        #    deg(track.az),
        #    deg(track.el),
        #    deg(nav.az),
        #    deg(nav.el),
        # )

        times, az, el = pos
        timer.settime(next(times).utc_datetime().timestamp(), absolute=True)
        self.rot.go(AzEl(next(az), next(el)))
        return True

    def on_rot_event(self, rot: Rotator, _event: int) -> bool:
        # this is currently only AzEl, but may be error in the future
        evt = rot.event()
        logger.info("on_rot_event: %s", evt)
        return True

    def on_rise(self, timer: linuxfd.timerfd, _event: int) -> bool:
        logger.info("AOS %s", timer.read())
        self.rad.set_tx_selector("edl")
        self.sta.ptt_on()

        self.edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.edl.bind(self.conf.edl)
        self.edl.settimeout(0.5)  # FIXME: nonblocking
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
        # index = time.searchsorted(now(), side='right')
        self.rad.edl(packet, self.current_rv)
        logger.info("Sent EDL")
        return True

    def on_rx_doppler(self, timer: linuxfd.timerfd, rv: Velocity, _event: int) -> bool:
        timer.read()
        times, range_velocities = rv
        timer.settime(next(times).utc_datetime().timestamp(), absolute=True)
        # FIXME: set doppler to point that minimizes error over the interval (midpoint?)
        self.current_rv = next(range_velocities)
        logger.debug("doppler %f", self.current_rv)
        self.rad.set_rx_frequency(self.current_rv)
        return True


class Commander:
    def __init__(self, conf: Config) -> None:
        '''Create the main pass coordinator.'''
        self.conf = conf
        self.track = Tracker(conf.observer, owmid=conf.owmid)

        # FIXME: should these go in config?
        self.max_temp = 30.0
        self.min_el = Angle(degrees=15)
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

    def sleep_until_next_pass(self, sat: Satellite | None = None) -> None:
        # FIXME: recompute passes every 24 hours/when a new TLE comes out?
        # FIXME: how many days is a tle good for? Set days_lookahead based on that
        # FIXME: now that we have an event loop can this be part of it?

        if sat is None:
            sat = Satellite(
                self.conf.sat_id, tle_cache=self.conf.tle_cache, local_only='con' in self.conf.mock
            )
        np = self.track.next_pass(sat, min_el=self.min_el)
        if np is None:
            # FIXME: sleep for 24h?
            raise RuntimeError("No pass found")
        to_sleep = timedelta(days=np.rise.time - self.track.ts.now())
        if to_sleep > timedelta():
            logger.info(
                "Sleeping %s until next rise time %s for a %.2f°el pass.",
                to_sleep,
                np.rise.time.astimezone(None),
                np.culm[0].el.degrees,
            )
            sleep(to_sleep.total_seconds())  # FIXME: wake up a bit before a pass to adjust TLEs?
        else:
            logger.info("In a pass now!")

    def autorun(self, count: int) -> None:
        logger.info("Running for %d passes", count)
        # FIXME: use scheduler to sleep to next pass
        while count > 0:
            self.require_clock_sync()

            sat = Satellite(
                self.conf.sat_id, tle_cache=self.conf.tle_cache, local_only='con' in self.conf.mock
            )
            self.sleep_until_next_pass(sat)
            # FIXME: How often are TLEs updated? should this be the same as days_lookahead?

            # FIXME: check.
            if self.track.ts.now() - sat.epoch > 1:
                sat = Satellite(
                    self.conf.sat_id,
                    tle_cache=self.conf.tle_cache,
                    local_only='con' in self.conf.mock,
                )
            np = self.track.next_pass(sat, min_el=self.min_el)
            if np is None:
                # FIXME: get np from sleep_until_next_pass and then go around the loop again?
                raise RuntimeError("No pass found")

            degc = self.singlepass.sta.gettemp()
            if degc > self.max_temp:
                logger.info(
                    "Temperature is too high (%f°C > %f°C). Skipping this pass.",
                    degc,
                    self.max_temp,
                )
                continue  # FIXME: sleep until end of current pass

            # Pre-compute pass time/alt/az/rv
            temp, pressure = self.track.weather()
            logger.info("Fetched temp/pressure")

            pos, rv = self.track.track(sat, np, temp, pressure)
            pos = self.singlepass.rot.path(np, pos)
            self.singlepass.work(pos, rv)

            seconds = timedelta(days=np.fall.time - self.track.ts.now()).total_seconds()
            if seconds > 0:
                logger.info("Sleeping %.3f seconds until pass is really over.", seconds)
                sleep(seconds)
            count -= 1

    # Testing stuff goes below here

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
        pos, (rvtime, rangevel) = self.track.track(sat, np)
        postime, az, el = self.singlepass.rot.path(np, pos)
        offset = postime[0] - self.track.ts.now()
        logger.info("Dryrun offset: %f", offset)
        self.singlepass.work((postime - offset, az, el), (rvtime - offset, rangevel))
        logger.info("Dry run complete")

    def test_morse(self) -> None:
        while True:
            self.singlepass.ident()
            sleep(30)
