import numpy as np
from skyfield.api import load
from skyfield.units import Angle

from pass_commander.navigator import Backhand, Flip, Navigator, Straight
from pass_commander.tracker import PassEvent, PassInfo

# FIXME: nav tracks should always start/end on el 0/180, or possibly AOS/LOS cutoff?


class TestNavigator:
    ts = load.timescale()

    def test_nav_straight(self) -> None:
        info = PassInfo(
            PassEvent(self.ts.now(), Angle(degrees=45), Angle(degrees=0)),
            [PassEvent(self.ts.now(), Angle(degrees=90), Angle(degrees=45))],
            PassEvent(self.ts.now(), Angle(degrees=135), Angle(degrees=0)),
        )

        nav = Navigator.mode(info)
        assert isinstance(nav, Straight)
        az, el = nav.azel(Angle(radians=np.full(2, 45.0)), Angle(radians=np.full(2, 45.0)))
        assert isinstance(az, Angle)
        assert isinstance(el, Angle)
        str(nav)

    def test_nav_backhand(self) -> None:
        info = PassInfo(
            PassEvent(self.ts.now(), Angle(degrees=350), Angle(degrees=0)),
            [PassEvent(self.ts.now(), Angle(degrees=0), Angle(degrees=45))],
            PassEvent(self.ts.now(), Angle(degrees=170), Angle(degrees=0)),
        )

        nav = Navigator.mode(info)
        assert isinstance(nav, Backhand)
        az, el = nav.azel(Angle(radians=np.full(2, 45.0)), Angle(radians=np.full(2, 45.0)))
        assert isinstance(az, Angle)
        assert isinstance(el, Angle)
        str(nav)

    def test_nav_flip(self) -> None:
        info = PassInfo(
            PassEvent(self.ts.now(), Angle(degrees=45), Angle(degrees=0)),
            [PassEvent(self.ts.now(), Angle(degrees=90), Angle(degrees=90))],
            PassEvent(self.ts.now(), Angle(degrees=135), Angle(degrees=0)),
        )

        nav = Navigator.mode(info)
        assert isinstance(nav, Flip)
        az, el = nav.azel(Angle(radians=np.full(2, 45.0)), Angle(radians=np.full(2, 45.0)))
        assert isinstance(az, Angle)
        assert isinstance(el, Angle)
        # FIXME: el is monotonic from 0 to 180 or viceversa
        str(nav)
