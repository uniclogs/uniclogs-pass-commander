from contextlib import closing

import pytest

from pass_commander.station import Station, StationError


class TestStation:
    def test_pa(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            assert s.pa_on().startswith('SUCCESS')
            assert s.pa_off().startswith('SUCCESS')

    def test_ptt(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            s.ptt_on().startswith('SUCCESS')
            s.ptt_off().startswith('SUCCESS')

    def test_getttemp(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            assert s.gettemp() == 25.0

    def test_lna(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd, lna_delay=0)) as s:
            assert s.lna_on().startswith('SUCCESS')
            assert s.lna_off().startswith('SUCCESS')

    def test_pa_ptt_conflict(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd)) as s:
            assert s.pa_on().startswith('SUCCESS')
            assert s.ptt_on().startswith('SUCCESS')
            with pytest.raises(StationError, match='PTT Conflict'):
                s.pa_off()

    def test_lna_ptt_conflict(self, stationd: tuple[str, int]) -> None:
        with closing(Station(stationd, lna_delay=0)) as s:
            assert s.ptt_on().startswith('SUCCESS')
            assert s.lna_on().startswith('FAIL')

    def test_invalid_station(self, stationd: tuple[str, int]) -> None:
        with (
            closing(Station(stationd, band='fakeband')) as s,
            pytest.raises(ValueError, match='invalid command'),
        ):
            assert s.pa_on().startswith('SUCCESS')
