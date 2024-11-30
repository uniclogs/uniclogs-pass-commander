from math import radians

from pass_commander.config import AzEl
from pass_commander.navigator import Navigator
from pass_commander.tracker import PassInfo


class TestNavigator:
    def test_nav_straight(self) -> None:
        nav = Navigator(PassInfo(0, radians(45), 0, 0, 0, radians(135), radians(90)))
        assert nav.nav_mode == nav.nav_straight
        nav.azel(AzEl(radians(45), radians(45)))

    def test_nav_backhand(self) -> None:
        nav = Navigator(PassInfo(0, radians(350), 0, 0, 0, radians(170), radians(80)))
        assert nav.nav_mode == nav.nav_backhand
        nav.azel(AzEl(radians(45), radians(45)))

    def test_nav_flip(self) -> None:
        nav = Navigator(PassInfo(0, radians(45), 0, radians(90), 0, radians(135), radians(90)))
        assert nav.nav_mode == nav.nav_flip
        nav.azel(AzEl(radians(45), radians(45)))
