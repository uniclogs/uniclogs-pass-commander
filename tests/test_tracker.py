from datetime import timedelta

from skyfield.api import E, N, wgs84

from pass_commander.satellite import Satellite
from pass_commander.tracker import Tracker


class TestTracker:
    def test_next_pass(self, sat: Satellite) -> None:
        track = Tracker(wgs84.latlon(45.509054 * N, -122.681394 * E, 50))
        np = track.next_pass(sat, after=sat.epoch)
        assert np.rise.time < np.culm[0].time < np.fall.time
        if np.fall.time - np.rise.time < (timedelta(hours=1) / timedelta(days=1)):
            track.track(sat, np)
