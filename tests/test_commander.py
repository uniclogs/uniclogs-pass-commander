# ruff: noqa: ERA001

import pytest
from skyfield.api import E, N, Time, wgs84
from skyfield.units import Angle, Velocity

from pass_commander.commander import Commander, SinglePass
from pass_commander.config import Config
from pass_commander.mock.flowgraph import Edl, Flowgraph
from pass_commander.mock.rotator import PtyRotator
from pass_commander.mock.station import Stationd
from pass_commander.satellite import Satellite
from pass_commander.tracker import Tracker


@pytest.fixture
def mock_config(
    good_config: Config,
    stationd: Stationd,
    rotator: PtyRotator,
    edl: Edl,
    flowgraph: Flowgraph,
) -> Config:
    '''Generate a config with all mock devices started.'''
    good_config.station = stationd
    good_config.rotator = rotator
    good_config.edl_dest = edl.addr
    good_config.flowgraph = flowgraph.addr
    return good_config


class TestSinglePass:
    def test_work_pass(self, mock_config: Config, sat: Satellite) -> None:
        sp = SinglePass(mock_config, lna_delay=0.0, morse_delay=0.0, cooloff_delay=0.0)
        sp.rot.cmd_interval = 0

        tk = Tracker(mock_config.observer)
        times = tk.next_pass(sat, sat.epoch)
        (pt, az, el), (rt, rv) = tk.track(sat, times)
        # now = tk.ts.now()
        # Start now
        # pt += now - pt[0]
        # rt += now - rt[0]
        #  1000x faster
        # pt *= 0.001
        # rt *= 0.001
        # FIXME: scale time to be quick
        pt -= 1000
        rt -= 1000

        sp.work((pt, az, el), (pt, az, el), (rt, rv))

    def test_over_thermal_limit(self, mock_config: Config, sat: Satellite) -> None:
        mock_config.temp_limit = 24.0
        sp = SinglePass(mock_config, lna_delay=0.0, morse_delay=0.0, cooloff_delay=0.0)
        sp.rot.cmd_interval = 0

        tk = Tracker(mock_config.observer)
        times = tk.next_pass(sat, sat.epoch)
        (pt, az, el), (rt, rv) = tk.track(sat, times)
        pt += 1000
        rt += 1000
        with pytest.raises(RuntimeError, match="^Temperature too high"):
            sp.work((pt, az, el), (pt, az, el), (rt, rv))


class TestCommander:
    def test_pointing_mode(self, mock_config: Config) -> None:
        class FakePass:
            def work(
                self,
                _pos: tuple[Time, Angle, Angle],
                nav: tuple[Time, Angle, Angle],
                _rv: tuple[Time, Velocity],
            ) -> None:
                self.target_az = nav[1].degrees[0]

        origin = wgs84.latlon(45 * N, -122 * E)
        mock_config.observer = origin

        cmdr = Commander(mock_config)
        cmdr.singlepass = FakePass()

        lat = origin.latitude.degrees
        lon = origin.longitude.degrees

        targets = [
            (wgs84.latlon(lat + 0.1, lon + 0.0), 0),  # North
            (wgs84.latlon(lat + 0.1, lon + 0.1), 45),  # NE
            (wgs84.latlon(lat + 0.1, lon - 0.1), 315),  # NW
            (wgs84.latlon(lat - 0.1, lon + 0.0), 180),  # South
            (wgs84.latlon(lat - 0.1, lon + 0.1), 135),  # SE
            (wgs84.latlon(lat - 0.1, lon - 0.1), 225),  # SW
            (wgs84.latlon(lat + 0.0, lon + 0.1), 90),  # East
            (wgs84.latlon(lat + 0.0, lon - 0.1), 270),  # West
        ]
        for target, expected_az in targets:
            cmdr.point(target)
            assert cmdr.singlepass.target_az == pytest.approx(expected_az)
