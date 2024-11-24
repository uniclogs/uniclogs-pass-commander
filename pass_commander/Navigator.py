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

import logging
from math import cos
from math import degrees as deg
from math import pi

from .config import AzEl
from .Tracker import PassInfo

logger = logging.getLogger(__name__)


class Navigator:
    """Navigator class for pass_commander"""

    def __init__(self, pass_info: PassInfo):
        rise_time = pass_info.rise_time
        rise_az = pass_info.rise_azimuth
        maxel_time = pass_info.maximum_altitude_time
        max_elevation = pass_info.maximum_altitude
        set_time = pass_info.set_time
        set_az = pass_info.set_azimuth
        maxel_az = pass_info.maximum_altitude_azimuth

        z = (abs(rise_az - maxel_az) + abs(maxel_az - set_az)) > (1.5 * pi)
        if self.no_zero_cross(rise_az, maxel_az, set_az):
            self.nav_mode = self.nav_straight
        elif self.no_zero_cross(*self.rot_pi((rise_az, maxel_az, set_az))):
            self.nav_mode = self.nav_backhand
        else:
            # This probably means we need to extend into the 450° operating area
            self.nav_mode = self.nav_straight  # FIXME

        logger.info(
            "rise:%s rise:%.3f°az maxel:%s max:%.3f°el set:%s set:%.3f°az",
            rise_time,
            deg(rise_az),
            maxel_time,
            deg(max_elevation),
            set_time,
            deg(set_az),
        )
        if deg(max_elevation) >= 78:
            self.flip_az = (rise_az - ((rise_az - set_az) / 2) + pi / 2) % (2 * pi)
            if self.az_n_hem(self.flip_az):
                (self.flip_az,) = self.rot_pi((self.flip_az,))
            self.nav_mode = self.nav_flip
            logger.info("Flip at %.3f", deg(self.flip_az))
        logger.info(
            "Zero_cross:%s mode:%s start:%s rise:%.3f°az peak:%.3f°az set:%.3f°az",
            z,
            self.nav_mode.__name__,
            rise_time,
            deg(rise_az),
            deg(maxel_az),
            deg(set_az),
        )

    def rot_pi(self, rad: tuple[float, ...]) -> tuple[float, ...]:
        """rotate any radian by half a circle"""
        return tuple((x + pi) % (2 * pi) for x in rad)

    def no_zero_cross(self, a: float, b: float, c: float) -> bool:
        return (a < b < c) or (a > b > c)

    def az_e_hem(self, az: float) -> bool:
        return az < pi

    def az_n_hem(self, az: float) -> bool:
        return cos(az) > 0

    def nav_straight(self, track: AzEl) -> AzEl:
        return track

    def nav_backhand(self, track: AzEl) -> AzEl:
        return AzEl((track.az + pi) % (2 * pi), pi - track.el)

    def nav_flip(self, track: AzEl) -> AzEl:
        flip_el = pi / 2 - (cos(track.az - self.flip_az) * (pi / 2 - track.el))
        return AzEl(self.flip_az, flip_el)

    def azel(self, track: AzEl) -> AzEl:
        nav = self.nav_mode(track)
        logger.info(
            '%-28s%7.3f°az %7.3f°el to %7.3f°az %7.3f°el',
            "Navigation corrected from",
            deg(track.az),
            deg(track.el),
            deg(nav.az),
            deg(nav.el),
        )
        return nav
