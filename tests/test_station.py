from contextlib import closing

from pass_commander.mock.station import Stationd
from pass_commander.station import Station


class TestStation:
    def test_pa(self, stationd: Stationd) -> None:
        with closing(Station(stationd)) as s:
            s.pa_on()
            s.pa_off()

    def test_ptt(self, stationd: Stationd) -> None:
        with closing(Station(stationd)) as s:
            s.ptt_on()
            s.ptt_off()

    def test_getttemp(self, stationd: Stationd) -> None:
        with closing(Station(stationd)) as s:
            s.gettemp()
