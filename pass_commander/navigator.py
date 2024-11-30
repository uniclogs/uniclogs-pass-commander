import logging
from math import cos, pi
from math import degrees as deg

from .config import AzEl
from .tracker import PassInfo

logger = logging.getLogger(__name__)


class Navigator:
    def __init__(self, pass_info: PassInfo) -> None:
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
        pass_info
            The specific satellite pass to determine navigation mode from
        '''
        rise_time = pass_info.rise_time
        rise_az = pass_info.rise_azimuth
        maxel_time = pass_info.maximum_altitude_time
        max_elevation = pass_info.maximum_altitude
        set_time = pass_info.set_time
        set_az = pass_info.set_azimuth
        maxel_az = pass_info.maximum_altitude_azimuth

        # Max elevation degrees above which to use nav mode flip.
        # FIXME This should be calculated from slew rate.
        flip_above = 78

        z = (abs(rise_az - maxel_az) + abs(maxel_az - set_az)) > (1.5 * pi)
        if self.no_zero_cross(rise_az, maxel_az, set_az):
            self.nav_mode = self.nav_straight
        elif self.no_zero_cross(*self.rot_pi((rise_az, maxel_az, set_az))):
            self.nav_mode = self.nav_backhand
        else:
            # FIXME This probably means we need to extend into the 450°
            # operating area
            self.nav_mode = self.nav_straight

        logger.info(
            "rise:%s rise:%.3f°az maxel:%s max:%.3f°el set:%s set:%.3f°az",
            rise_time,
            deg(rise_az),
            maxel_time,
            deg(max_elevation),
            set_time,
            deg(set_az),
        )
        if deg(max_elevation) >= flip_above:
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
        """Rotate any radian by half a circle."""
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
