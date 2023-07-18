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


import ephem
from math import cos, degrees as deg


class Navigator:
    """Navigator class for pass_commander"""

    def __init__(
        self, track, rise_time, rise_az, maxel_time, max_elevation, set_time, set_az
    ):
        self.track = track
        self.rise_time = rise_time
        self.rise_az = rise_az
        self.maxel_time = maxel_time
        self.max_elevation = max_elevation
        self.set_time = set_time
        self.set_az = set_az

        self.maxel_az = self.track.az_at_time(maxel_time)
        z = (abs(rise_az - self.maxel_az) + abs(self.maxel_az - set_az)) > (
            1.5 * ephem.pi
        )
        if self.no_zero_cross(rise_az, self.maxel_az, set_az):
            self.nav_mode = self.nav_straight
        elif self.no_zero_cross(*self.rot_pi((rise_az, self.maxel_az, set_az))):
            self.nav_mode = self.nav_backhand
        else:
            self.nav_mode = self.nav_straight  # FIXME
            """ This probably means we need to extend into the 450° operating area """
        # print('rise:%s rise:%.3f°az maxel:%s max:%.3f°el set:%s set:%.3f°az'%(rise_time, deg(rise_az), maxel_time, deg(max_elevation), set_time, deg(set_az)))
        print(
            f"rise:{rise_time} rise:{deg(rise_az):.3f}°az maxel:{maxel_time} "
            f"max:{deg(max_elevation):.3f}°el set:{set_time} set:{deg(set_az):.3f}°az"
        )
        if deg(max_elevation) >= 78:
            self.flip_az = (
                self.rise_az - ((self.rise_az - self.set_az) / 2) + ephem.pi / 2
            ) % (2 * ephem.pi)
            if self.az_n_hem(self.flip_az):
                self.flip_az = self.rot_pi(self.flip_az)
            self.nav_mode = self.nav_flip
            print(f"Flip at {deg(self.flip_az):.3f}")
        # print('Zero_cross:%r mode:%s start:%s rise:%.3f°az peak:%.3f°az set:%.3f°az' %
        #        (z, self.nav_mode.__name__, rise_time, deg(rise_az), deg(self.maxel_az), deg(set_az)))
        print(
            f"Zero_cross:{z} mode:{self.nav_mode.__name__} start:{rise_time} "
            f"rise:{deg(rise_az):.3f}°az peak:{deg(self.maxel_az):.3f}°az set:{deg(set_az):.3f}°az"
        )

    def rot_pi(self, rad):
        """rotate any radian by half a circle"""
        if type(rad) == tuple:
            return tuple([(x + ephem.pi) % (2 * ephem.pi) for x in rad])
        return (rad + ephem.pi) % (2 * ephem.pi)

    def no_zero_cross(self, a, b, c):
        return (a < b < c) or (a > b > c)

    def az_e_hem(self, az):
        return az < ephem.pi

    def az_n_hem(self, az):
        return cos(az) > 0

    def nav_straight(self, azel):
        return azel

    def nav_backhand(self, azel):
        (input_az, input_el) = azel
        return ((input_az + ephem.pi) % (2 * ephem.pi), ephem.pi - input_el)

    def nav_flip(self, azel):
        (input_az, input_el) = azel
        flip_el = ephem.pi / 2 - (
            cos(input_az - self.flip_az) * (ephem.pi / 2 - input_el)
        )
        return (self.flip_az, flip_el)

    def azel(self, azel):
        navazel = self.nav_mode(azel)
        # print('Navigation corrected from \t% 3.3f°az % 3.3f°el to % 3.3f°az % 3.3f°el' % tuple(deg(x) for x in (*azel, *navazel)))
        print(
            f'{"Navigation corrected from": <28}{deg(azel[0]): >7.3f}°az {deg(azel[1]): >7.3f}°el to {deg(navazel[0]): >7.3f}°az {deg(navazel[1]): >7.3f}°el'
        )
        return navazel
