from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

import requests
from skyfield.api import Time, load
from skyfield.units import Angle, Velocity

if TYPE_CHECKING:
    from skyfield.toposlib import GeographicPosition

    from .satellite import Satellite

logger = logging.getLogger(__name__)


class PassEvent(NamedTuple):
    time: Time
    az: Angle
    el: Angle


# While skyfield is capable of array math the interesting events in a pass
# are of low numbers and clarity is more important
# FIXME: could this just be Navigator?
# FIXME: should it know of ts so I can say time_to_rise() -> timedelta
@dataclass
class PassInfo:
    rise: PassEvent
    culm: list[PassEvent]
    fall: PassEvent


class Tracker:
    def __init__(
        self,
        observer: GeographicPosition,
        *,
        owmid: str = '',
    ) -> None:
        '''Tracks a satellite relative to a given observer.

        Given (or told to fetch) a TLE, it can handle temperature and pressure calibration,
        determining when the next pass will be, current satellite location, and doppler scaling.

        Parameters
        ----------
        observer
            The latitude, longitude, and altitude of the observer.
        owmid
            Open Weather Map API key, or empty string for none.
        '''
        self.owmid = owmid
        self.obs = observer
        self.ts = load.timescale()

    def _build_passinfo(self, sat: Satellite, times: list[Time]) -> PassInfo:
        events = []
        for t in times:
            # Not compensating for temperature/pressure because the culm could be well in the future
            # Recomputed later accounting for them in track()
            el, az, _ = (sat - self.obs).at(t).altaz()
            events.append(PassEvent(t, az, el))
        return PassInfo(events[0], events[1:-1], events[-1])

    # FIXME: filtering by time of day
    def next_pass(  # noqa: C901
        self,
        sat: Satellite,
        after: Time | None = None,
        min_el: Angle | None = None,
        lookahead: timedelta = timedelta(days=3),
    ) -> PassInfo | None:
        if after is None:
            after = self.ts.now()

        if min_el is None:
            min_el = Angle(degrees=15)

        # Find all passes above 0°. find_events() does have an elevation argument but that returns
        # times at the given elevation and we want the times where it crosses the horizon, 0°.
        times, events = sat.find_events(self.obs, after, after + lookahead)
        if not times:
            logger.error("No pass found in the next %d", lookahead)
            logger.info("The TLE or station location is fishy.")
            return None

        # Events are the following integers
        RISE = 0  # Satellite rises above 0° # noqa: N806
        CULM = 1  # Satellite is at an elevation local maxima # noqa: N806, F841
        FALL = 2  # Satellite falls below 0° # noqa: N806

        # Split the times list by pass, which is [RISE, one or more CULM, FALL], but we may be in a
        # pass so pre-fill the missing parts for the first entry.
        passes = []
        singlepass = []
        # `after` may be during a pass so we don't have an initial RISE/CULM
        if events[0] != RISE:
            # Some time during a pass
            singlepass.append(after)
        if events[0] == FALL:
            # Past the final culmination so `after` is the max elevation
            singlepass.append(after)

        for t, e in zip(times, events, strict=True):
            singlepass.append(t)
            if e == FALL:
                passes.append(singlepass)
                singlepass = []

        # The pass may end after the look-ahead time, so truncate. Either the orbit is unusual,
        # like a geosynchronous orbit, or the user should wait and recompute with the next
        # available TLE
        # FIXME: this is kind of unsatisfactory, the user may have to recompute during a pass.
        # Is there a better way of handling this?
        if events[-1] == RISE:
            singlepass.append(after + lookahead)
        if events[-1] != FALL:
            singlepass.append(after + lookahead)
            passes.append(singlepass)
            # FIXME: log.warn on truncation, but only if it's the only pass and only if
            # it's above min_el

        # Find the next pass with culmination greater than min_el
        for singlepass in passes:
            info = self._build_passinfo(sat, singlepass)
            for culm in info.culm:
                if culm.el.radians >= min_el.radians:
                    return info

        logger.warning(
            "No passes for %s in the next %s with elevation >=%.1f°",
            sat.name,
            lookahead,
            min_el.degrees,
        )
        return None

    def weather(self) -> tuple[float, float]:
        if not self.owmid:
            # From the ephem docs, temperature defaults to 25 C, pressure defaults to 1010 mBar
            logger.info("not fetching weather for calibration")
            return (25.0, 1010.0)
        # See https://openweathermap.org/api/one-call-3
        # FIXME: Rate limit 1 per mintue/1000 per day
        r = requests.get(
            'https://api.openweathermap.org/data/3.0/onecall',
            params={
                'lat': f'{self.obs.latitude.degrees:.3f}',
                'lon': f'{self.obs.longitude.degrees:.3f}',
                'exclude': 'minutely,hourly,daily,alerts',
                'units': 'metric',
                'appid': self.owmid,
            },
            timeout=10,
        )
        r.raise_for_status()
        logger.debug("Weather response: %s", r.json())
        c = r.json()["current"]
        return (c['temp'], c['pressure'])

    def track(
        self, sat: Satellite, singlepass: PassInfo, temp: float = 25.0, pressure: float = 1010.0
    ) -> tuple[tuple[Time, Angle, Angle], tuple[Time, Velocity]]:
        """Create a track of a given satellite relative to the set observer.

        Note that as the satellite is approaching the observer the rangevel is negative, and as it's
        moving away the value is positive.
        """
        rise = singlepass.rise.time
        fall = singlepass.fall.time

        pass_duration_seconds = (fall - rise) * 24 * 60 * 60
        passtimes = self.ts.linspace(rise, fall, int(pass_duration_seconds / 2))
        positions = (sat - self.obs).at(passtimes)

        el, az, _ = positions.altaz(temperature_C=temp, pressure_mbar=pressure)
        rangevel = positions.frame_latlon_and_rates(self.obs)[-1]
        # FIXME: separate functions for azel/rangevel?
        # Ideally the radio and the rotator should figure out the timesteps they need
        # Really they should have uniform steps in their required values and time should
        # be the variable but that's not the expected way - hard to do.
        return ((passtimes, az, el), (deepcopy(passtimes), rangevel))
