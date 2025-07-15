from __future__ import annotations

import logging
from abc import ABCMeta, abstractmethod
from math import cos, pi
from math import degrees as deg
from typing import TYPE_CHECKING

import numpy as np
from skyfield.units import Angle

if TYPE_CHECKING:
    from .tracker import PassInfo

logger = logging.getLogger(__name__)


class Navigator(metaclass=ABCMeta):
    def __init__(self, info: PassInfo) -> None:
        '''Determine rotator position from a given pass.

        As the satellite tracks across the sky, its specific path might exceed
        the slew rate of the rotator, or move beyond the bounds that the
        rotator can reach. There are multiple rotator orientations that point
        at the same spot in the sky though so this class tries to choose the
        correct orientation that keeps the rotator within its limits.

        The three navigation modes currently implemented:
        - normal: The rotator points at the track in a 1-to-1 manner
        - backhand: If az crosses from 0 to 360 this mode inverts the az and
              mirrors the el, so that az should pass through the other side
        - flip: If el is too high, crossing overhead will cause az to traverse
              too quickly. This fixes az at the middle point and moves only el

        Parameters
        ----------
        info
            The specific satellite pass to determine navigation mode from
        '''
        self.info = info

    @classmethod
    def mode(cls, info: PassInfo) -> Navigator:
        # FIXME: This assumes a single culmination
        # Max elevation degrees above which to use nav mode flip.
        # FIXME: This should be calculated from slew rate.
        flip_above = 78

        if info.culm[0].el.degrees >= flip_above:
            return Flip(info)
        if cls.no_zero_cross(info.rise.az.radians, info.culm[0].az.radians, info.fall.az.radians):
            return Straight(info)
        if cls.no_zero_cross(
            *cls.rot_pi((info.rise.az.radians, info.culm[0].az.radians, info.fall.az.radians))
        ):
            return Backhand(info)
        # FIXME This probably means we need to extend into the 450°
        # operating area
        logger.warning("Path and inverse both cross zero, defaulting to straight")
        return Straight(info)

    def __str__(self) -> str:
        rise = self.info.rise.az.radians
        culm = self.info.culm[0].az.radians
        fall = self.info.fall.az.radians

        rise_time = self.info.rise.time.astimezone(None)
        culm_time = self.info.culm[0].time.astimezone(None)
        fall_time = self.info.fall.time.astimezone(None)

        z = (abs(rise - culm) + abs(culm - fall)) > (1.5 * pi)
        return ''.join(
            f"rise: {rise_time} {deg(rise):.1f}°az\n"
            f"culm: {culm_time} {deg(culm):.1f}°el\n"
            f"fall: {fall_time} {deg(fall):.1f}°az\n"
            f"Zero_cross: {z} mode: {self.__class__.__name__}",
        )

    @staticmethod
    def rot_pi(rad: tuple[float, ...]) -> tuple[float, ...]:
        """Rotate any radian by half a circle."""
        return tuple((x + pi) % (2 * pi) for x in rad)

    @staticmethod
    def no_zero_cross(a: float, b: float, c: float) -> bool:
        return (a < b < c) or (a > b > c)

    @staticmethod
    def az_n_hem(az: float) -> bool:
        return cos(az) > 0

    @abstractmethod
    def azel(self, az: Angle, el: Angle) -> tuple[Angle, Angle]:
        pass


class Straight(Navigator):
    def azel(self, az: Angle, el: Angle) -> tuple[Angle, Angle]:
        return (az, el)


class Backhand(Navigator):
    def azel(self, az: Angle, el: Angle) -> tuple[Angle, Angle]:
        return ((az.radians + pi) % (2 * pi), pi - el.radians)


class Flip(Navigator):
    def __init__(self, info: PassInfo) -> None:
        '''Navigation strategy that primarily rotates el and trys to minimize az.

        This prevents the wrist flip problem in high angle passes.

        Parameters
        ----------
        info
            The parameters of the pass to plan for
        '''
        super().__init__(info)
        # halfway point between rise and (fall + halfcircle)
        # FIXME: verify average works on circle
        flip_az = ((info.rise.az.radians + info.fall.az.radians + pi) / 2) % (2 * pi)
        # FIXME: I can't convince myself that this is correct yet
        if self.az_n_hem(flip_az):
            (flip_az,) = self.rot_pi((flip_az,))

        self.flip_az = Angle(radians=flip_az)

    def azel(self, az: Angle, el: Angle) -> tuple[Angle, Angle]:
        # FIXME: what even is this
        flip_el = pi / 2 - (np.cos(az.radians - self.flip_az.radians) * (pi / 2 - el.radians))
        return (Angle(radians=np.full(len(flip_el), self.flip_az.radians)), Angle(radians=flip_el))

    def __str__(self) -> str:
        val = super().__str__()
        val += f" at {self.flip_az.degrees:.1f}°az"
        return val
