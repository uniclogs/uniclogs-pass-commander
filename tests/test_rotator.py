import unittest

from pass_commander.config import AzEl
from pass_commander.rotator import Rotator


class TestRotator(unittest.TestCase):
    def test_go(self) -> None:
        rot = Rotator(None)
        rot.go(AzEl(20, 20))
        self.assertEqual(rot.position(), AzEl(20, 20))
        rot.go(AzEl(10, 10))
        self.assertEqual(rot.position(), AzEl(10, 10))
        rot.go(AzEl(0, 0))
        self.assertEqual(rot.position(), AzEl(0, 0))

    def test_park(self) -> None:
        rot = Rotator(None)
        rot.park()
        self.assertEqual(rot.position(), AzEl(180, 90))
