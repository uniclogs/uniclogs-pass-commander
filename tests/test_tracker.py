from datetime import timedelta

import responses
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

    @responses.activate
    def test_weather(self) -> None:
        lat = 45.509054
        lon = -122.681394
        track = Tracker(wgs84.latlon(lat * N, lon * E, 50))
        # No owmid, returns default, should not make a request
        assert track.weather() == (25.0, 1010.0)

        # With owmid it should make a request
        track.owmid = "testid"
        weather = (2.0, 994.0)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                url='https://api.openweathermap.org/data/3.0/onecall',
                match=[
                    responses.matchers.query_param_matcher(
                        {"lat": f"{lat:.3f}", "lon": f"{lon:.3f}", "appid": track.owmid},
                        strict_match=False,
                    )
                ],
                body=f'{{"current": {{"temp": {weather[0]}, "pressure": {weather[1]}}}}}',
            )
            assert track.weather() == weather
