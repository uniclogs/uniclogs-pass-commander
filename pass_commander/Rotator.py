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

from __future__ import annotations

import logging
from numbers import Real
from typing import Optional, Union

import Hamlib

from .config import AzEl

logger = logging.getLogger(__name__)


class RotatorError(Exception):
    def __init__(self, arg: Union[Hamlib.Rot, str]):
        if isinstance(arg, Hamlib.Rot):
            arg = Hamlib.rigerror(arg.error_status)
        super().__init__(arg)


class Bound:
    def __init__(self, lower: Real, upper: Real):
        self.lower = lower
        self.upper = upper

    def shift(self, x: Real) -> Bound:
        self.lower -= x
        self.upper -= x
        return self

    def clamp(self, x: Real) -> Real:
        return min(max(x, self.lower), self.upper)


class Rotator:
    def __init__(self, host: Optional[str], port: int = 4533, cal: AzEl = AzEl(0, 0)):
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
        self.last_reported: Optional[AzEl] = None

    @property
    def is_moving(self) -> bool:
        return self._moving

    def position(self) -> AzEl:
        # This consistently returns the last requested az/el, not present location
        now = AzEl(*self.rot.get_position())
        # Second request gives us the actual present location - FIXME: why?
        now = AzEl(*self.rot.get_position())
        return now

    def go(self, pos: AzEl) -> None:
        try:
            now = self.position()
        except RuntimeError as e:
            raise RotatorError(self.rot) from e

        if self.is_moving and now == self.last_reported:
            raise RotatorError("Rotator movement failed")

        az = self.lim.az.clamp(pos.az)
        el = self.lim.el.clamp(pos.el)

        if abs(az - now.az) > 5 or abs(el - now.el) > 3:
            logger.info(
                '%-18s%7.3f°az %7.3f°el to %7.3f°az %7.3f°el', "Moving from", now.az, now.el, az, el
            )
            self._moving = True
            self.rot.set_position(az, el)
            self.last_reported = now
        else:
            self._moving = False

    def park(self) -> None:
        # TODO rot.park()?
        self.go(AzEl(180, 90))
