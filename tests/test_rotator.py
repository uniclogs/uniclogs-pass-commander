import selectors
from contextlib import closing
from math import isclose

import pytest

from pass_commander.config import AzEl
from pass_commander.mock.rotator import PtyRotator
from pass_commander.rotator import Rotator


class TestRotator:
    @pytest.fixture
    def rot(self, rotator: PtyRotator) -> Rotator:
        with closing(Rotator(rotator)) as r:
            yield r

    def test_go(self, rot: Rotator) -> None:
        sel = selectors.DefaultSelector()
        sel.register(rot.listener, selectors.EVENT_READ, None)

        for pos in (
            AzEl(20, 20),
            AzEl(10.1, 10.4),
            AzEl(0, 0),
            AzEl(14.555346144996733, 0.4611240576248191),
        ):
            rot.go(pos)
            sel.select()
            event = rot.event()
            assert isinstance(event, AzEl)
            # FIXME: see rotator.py _ppd comment. Remove 0.1 when fixed
            assert isclose(event.az, pos.az, rel_tol=0, abs_tol=1 / rot.ppd + 0.1)
            assert isclose(event.el, pos.el, rel_tol=0, abs_tol=1 / rot.ppd + 0.1)

    def test_double_go(self, rot: Rotator) -> None:
        rot.go(AzEl(0, 0))
        rot.go(AzEl(0, 0))

    def test_park(self, rot: Rotator) -> None:
        rot.park()
        assert rot.position() == AzEl(180, 90)

    def test_limits(self, rot: Rotator) -> None:
        az, el = rot.limits()
        good = [AzEl(az.lower, 0), AzEl(az.upper, 0), AzEl(0, el.lower), AzEl(0, el.upper)]
        bad = [
            AzEl(az.lower - 1, 0),
            AzEl(az.upper + 1, 0),
            AzEl(0, el.lower - 1),
            AzEl(0, el.upper + 1),
        ]

        for azel in good:
            rot.go(azel)
        for azel in bad:
            with pytest.raises(ValueError, match="out of range"):
                rot.go(azel)
