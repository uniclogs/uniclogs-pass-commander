from contextlib import closing

import pytest

from pass_commander.station import Station, StationError


class TestStation:
    def test_pa(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            s.pa_on()
            s.pa_off()

    def test_ptt(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            s.ptt_on()
            s.ptt_off()

    def test_getttemp(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            assert s.gettemp() == 25.0

    def test_lna(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd, lna_delay=0)) as s:
            s.lna_on()
            s.lna_off()

    def test_pa_ptt_conflict(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            s.pa_on()
            s.ptt_on()
            with pytest.raises(StationError, match='PTT Conflict'):
                s.pa_off()

    def test_lna_ptt_conflict(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd, lna_delay=0)) as s:
            s.ptt_on()
            with pytest.raises(StationError):
                s.lna_on()

    def test_invalid_station(self, stationd: tuple[str, int]) -> None:
        with (
            closing(Station(stationd, band='fakeband')) as s,
            pytest.raises(StationError, match='invalid command'),
        ):
            s.pa_on()
