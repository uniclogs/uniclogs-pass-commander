# ruff: noqa: ERA001
from __future__ import annotations

import logging
import os
import struct
from time import sleep
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING

import rot2prog

from .config import AzEl
from .navigator import Navigator

if TYPE_CHECKING:
    from pathlib import Path

    from skyfield.units import Angle, Time

    from .tracker import PassInfo


logger = logging.getLogger(__name__)


class RotatorError(Exception):
    def __init__(self, arg: str) -> None:
        '''Exceptions raised by Rotator.

        If arg is Hamlib.Rot it will attempt to retrieve the error from the library
        '''
        super().__init__(arg)


class Bound:
    def __init__(self, lower: float, upper: float) -> None:
        '''Clamp a value value to a given range.'''
        self.lower = lower
        self.upper = upper

    def shift(self, x: float) -> Bound:
        return Bound(self.lower + x, self.upper + x)

    def clamp(self, x: float) -> float:
        return min(max(x, self.lower), self.upper)

    def __contains__(self, item: float) -> bool:
        return self.lower <= item <= self.upper

    def __str__(self) -> str:
        return f'[{self.lower},{self.upper}]'


class Rotator:
    def __init__(self, path: Path, cal: AzEl = AzEl(0, 0)) -> None:
        '''Monitor and point an antenna.

        The antenna has maximum and minimum az/el and also a minimum rotation
        step size. Also hamlib is weird and limited so this tries to paper over
        some of that and detects when the antenna is moving.

        Parameters
        ----------
        path
            path to rotator serial device, e.g. /dev/ttyS0
        cal
            Rotator offsets to apply, e.g. if the physical antenna has been turned.
        '''
        self.cal = cal  # FIXME: implement
        # FIXME: set from beamwidth/slew rate/actual min step size?
        # do we actually need a min step size?
        # should azel be filtered to min step?
        # should this be a config option?
        self.step = AzEl(5, 3)  # Minimum rotator stepsize

        # FIXME: only open during pass/close after. Also check mode
        self._rot = rot2prog.ROT2Prog(str(path))
        self.ppd = self._rot.get_pulses_per_degree()
        # FIXME: adjusting bounds by 0.1 is a hack to get around floating point
        # noise but it should be below the controller resolution so I don't think
        # it's incorrect. Need to verify behavior on the actual controller
        self._ppd = Bound(round(-1 / self.ppd, 1) - 0.1, round(1 / self.ppd, 1) + 0.1)
        self._rotlock = Lock()

        self._stop: Event | None = None
        self._thread: Thread | None = None
        self._r, self._w = os.pipe2(os.O_NONBLOCK)

    @property
    def listener(self) -> int:
        return self._r

    def _events(self, pos: AzEl) -> None:
        # Only runs from go to commanded position
        self._stop = Event()
        last_reported = None
        while True:
            # Either the controller or rot2prog doesn't like back-to-back commands, times out if
            # status is called too early after go. This time is the shortest measured empirically
            # time that won't cause a timeout.
            sleep(0.4)
            try:
                with self._rotlock:
                    now = AzEl(*self._rot.status())
            except RuntimeError as e:
                # FIXME: what errors does status actually raise?
                # FIXME: write error to _w
                raise RotatorError("Rotator status failed") from e
            if now == last_reported:
                # FIXME: write error to _w
                raise RotatorError("Rotator movement failed")
            last_reported = now

            # standard com:
            # - event when rotator nears target
            # errors:
            # - Rotator not moving when it should be
            # - Serial communication failure

            if now.az in self._ppd.shift(pos.az) and now.el in self._ppd.shift(pos.el):
                os.write(self._w, struct.pack("ff", now.az, now.el))
                self._stop.set()

            if self._stop.wait(timeout=0.5):
                break
        self._stop = None

    def event(self) -> AzEl:
        return AzEl(*struct.unpack('ff', os.read(self.listener, 8)))

    def limits(self) -> tuple[Bound, Bound]:
        with self._rotlock:
            lim = self._rot.get_limits()
        return (Bound(lim[0], lim[1]), Bound(lim[2], lim[3]))

    def go(self, pos: AzEl) -> None:
        az, el = pos
        logger.info('%-18s%7.3f°az %7.3f°el', "Moving to", az, el)
        with self._rotlock:
            # FIXME: check result
            self._rot.set(az, el)

        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self._thread = Thread(target=self._events, args=(pos,), name=f"Rotator-{az:.1f}-{el:.1f}")
        self._thread.start()

    def position(self) -> AzEl:
        with self._rotlock:
            return AzEl(*self._rot.status())

    def park(self) -> None:
        self.go(AzEl(180, 90))

    def path(self, np: PassInfo, pos: tuple[Time, Angle, Angle]) -> tuple[Time, Angle, Angle]:
        time, az, el = pos
        # sat az/el to rotator movement
        # TODO: filter by stepsize
        # FIXME: error on clamp?
        # lim = self.limits()
        nav = Navigator.mode(np)
        logger.info("Nav mode:\n%s", nav)
        az, el = nav.azel(az, el)
        # az = lim.az.clamp(az)
        # el = lim.el.clamp(el)

        return time, az, el

    def close(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._rotlock:
            self._rot._ser.close()  # noqa: SLF001
