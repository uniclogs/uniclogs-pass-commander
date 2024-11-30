from pass_commander.mock import Stationd
from pass_commander.station import Station


class TestStation:
    def test_pa(self) -> None:
        addr = ("127.0.0.2", 5006)
        Stationd(*addr).start()
        station = Station(*addr)

        station.pa_on()
        station.pa_off()

        station.close()

    def test_ptt(self) -> None:
        addr = ("127.0.0.2", 5007)
        Stationd(*addr).start()
        station = Station(*addr)

        station.ptt_on()
        station.ptt_off()

        station.close()

    def test_getttemp(self) -> None:
        addr = ("127.0.0.2", 5008)
        Stationd(*addr).start()
        station = Station(*addr)

        station.gettemp()

        station.close()
