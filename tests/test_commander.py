# ruff: noqa: ERA001

import pytest

from pass_commander.commander import SinglePass
from pass_commander.config import Config
from pass_commander.mock.flowgraph import Edl, Flowgraph
from pass_commander.mock.rotator import PtyRotator
from pass_commander.mock.station import Stationd
from pass_commander.satellite import Satellite
from pass_commander.tracker import Tracker


class TestSinglePass:
    @pytest.fixture
    def mock_config(
        self,
        good_config: Config,
        stationd: Stationd,
        rotator: PtyRotator,
        edl: Edl,
        flowgraph: Flowgraph,
    ) -> Config:
        good_config.station = stationd
        good_config.rotator = rotator
        good_config.edl = edl.addr
        good_config.flowgraph = flowgraph.addr
        return good_config

    def test_work_pass(self, mock_config: Config, sat: Satellite) -> None:
        sp = SinglePass(mock_config, lna_delay=0.0, morse_delay=0.0, cooloff_delay=0.0)

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

        sp.work((pt, az, el), (rt, rv))
