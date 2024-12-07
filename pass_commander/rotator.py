from __future__ import annotations

import logging

import Hamlib

from .config import AzEl

logger = logging.getLogger(__name__)


class RotatorError(Exception):
    def __init__(self, arg: Hamlib.Rot | str) -> None:
        '''Exceptions raised by Rotator.

        If arg is Hamlib.Rot it will attempt to retrieve the error from the library
        '''
        if isinstance(arg, Hamlib.Rot):
            arg = Hamlib.rigerror(arg.error_status)
        super().__init__(arg)


class Bound:
    def __init__(self, lower: float, upper: float) -> None:
        '''Clamp a value value to a given range.'''
        self.lower = lower
        self.upper = upper

    def shift(self, x: float) -> Bound:
        self.lower -= x
        self.upper -= x
        return self

    def clamp(self, x: float) -> float:
        return min(max(x, self.lower), self.upper)


class Rotator:
    def __init__(self, host: str | None, port: int = 4533, cal: AzEl = AzEl(0, 0)) -> None:
        '''Monitor and point an antenna.

        The antenna has maximum and minimum az/el and also a minimum rotation
        step size. Also hamlib is weird and limited so this tries to paper over
        some of that and detects when the antenna is moving.

        Parameters
        ----------
        host
            IP address of netrotctl or None for the simulated dummy rotator
        port
            Port that netrotctl is listening on
        cal
            Rotator offsets to apply, e.g. if the physical antenna has been turned.
        '''
        self.step = AzEl(5, 3)  # Minimum rotator stepsize

        Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE)  # FIXME: hook up to verbose
        if host is None:
            self.rot = Hamlib.Rot(Hamlib.ROT_MODEL_DUMMY)
        else:
            self.rot = Hamlib.Rot(Hamlib.ROT_MODEL_NETROTCTL)
            self.rot.set_conf("rot_pathname", f"{host}:{port}")
        self.rot.do_exception = True  # I recoil, visibly, in horror
        self._moving = False

        try:
            self.rot.open()
        except RuntimeError as e:
            raise RotatorError(self.rot) from e
        self.rot.state.az_offset = cal.az
        self.rot.state.el_offset = cal.el
        self.lim = AzEl(
            Bound(self.rot.state.min_az, self.rot.state.max_az).shift(cal.az),
            Bound(self.rot.state.min_el, self.rot.state.max_el).shift(cal.el),
        )
        self.last_reported: AzEl | None = None

    @property
    def is_moving(self) -> bool:
        return self._moving

    def position(self) -> AzEl:
        # This consistently returns the last requested az/el, not present location
        AzEl(*self.rot.get_position())
        # Second request gives us the actual present location - FIXME: why?
        return AzEl(*self.rot.get_position())

    def go(self, pos: AzEl) -> None:
        try:
            now = self.position()
        except RuntimeError as e:
            raise RotatorError(self.rot) from e

        if self.is_moving and now == self.last_reported:
            raise RotatorError("Rotator movement failed")

        az = self.lim.az.clamp(pos.az)
        el = self.lim.el.clamp(pos.el)

        if abs(az - now.az) > self.step.az or abs(el - now.el) > self.step.el:
            logger.info(
                '%-18s%7.3f°az %7.3f°el to %7.3f°az %7.3f°el',
                "Moving from",
                now.az,
                now.el,
                az,
                el,
            )
            self._moving = True
            self.rot.set_position(az, el)
            self.last_reported = now
        else:
            self._moving = False

    def park(self) -> None:
        # TODO rot.park()?
        self.go(AzEl(180, 90))
