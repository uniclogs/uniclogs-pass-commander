from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import degrees as deg
from pathlib import Path
from time import sleep

import ephem
import requests

from .config import AzEl, TleCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PassInfo:
    '''See https://rhodesmill.org/pyephem/quick.html#transit-rising-and-setting next_pass().

    This turns the returned tuple into something with names, and adds the maximum_altitude_azimuth
    field to record the asimuth at maximum_altitude.
    '''

    rise_time: ephem.Date
    rise_azimuth: ephem.Angle
    maximum_altitude_time: ephem.Date
    maximum_altitude: ephem.Angle
    set_time: ephem.Date
    set_azimuth: ephem.Angle
    maximum_altitude_azimuth: ephem.Angle


class Tracker:
    def __init__(
        self,
        observer: tuple[ephem.Angle, ephem.Angle, int],
        sat_id: str,
        *,
        local_only: bool = False,
        tle_cache: TleCache | None = None,
        owmid: str = '',
    ) -> None:
        '''Tracks a satellite relative to a given observer.

        Given (or told to fetch) a TLE, it can handle temperature and pressure calibration,
        determining when the next pass will be, current satellite location, and doppler scaling.

        Parameters
        ----------
        observer
            The (latitude, longitude, altitude) of the observer.
        sat_id
            The ID of the satellite, either as an International Designator, a NORAD Satellite
            Catalog number, or Catalog satellite name.
        local_only
            If true, do not attempt to the internet for TLE lookup, only tle_cache or Gpredict.
        tle_cache
            A local cache of TLEs for lookup.
        owmid
            Open Weather Map API key, or empty string for none.
        '''
        self.sat_id = sat_id
        self.local_only = local_only
        self.tle_cache = tle_cache
        self.owmid = owmid
        m = re.match(r"(?:20)?(\d\d)-?(\d{3}[A-Z])$", self.sat_id.upper())
        if m:
            year, launch = m.groups()
            self.sat_id = f"20{year}-{launch}"
            self.query = "INTDES"
        elif re.match(r"\d{5}$", self.sat_id):
            self.query = "CATNR"
        else:
            self.query = "NAME"
        self.obs = ephem.Observer()
        (self.obs.lat, self.obs.lon, self.obs.elev) = observer
        self.sat = ephem.readtle(*self.fetch_tle())

    def fetch_tle(self) -> list[str]:
        if self.local_only and self.tle_cache and self.sat_id in self.tle_cache:
            logger.info("using cached TLE")
            tle = self.tle_cache[self.sat_id]
        elif self.local_only and self.query == "CATNR":
            fname = Path.home() / '.config/Gpredict/satdata{self.sat_id}.sat'
            if fname.is_file():
                logger.info("using Gpredict's cached TLE")
                with fname.open(encoding="ascii") as file:
                    lines = file.readlines()[3:6]
                    tle = [line.rstrip().split("=")[1] for line in lines]
        elif self.local_only:
            logger.info("No matching TLE is available locally")
        else:
            tle = requests.get(
                f"https://celestrak.org/NORAD/elements/gp.php?{self.query}={self.sat_id}",
                timeout=10,
            ).text.splitlines()
            if tle[0] == "No GP data found":
                if self.tle_cache and self.sat_id in self.tle_cache:
                    logger.info("No results for %s at celestrak, using cached TLE", self.sat_id)
                    tle = self.tle_cache[self.sat_id]
                else:
                    raise ValueError(f"Invalid satellite identifier: {self.sat_id}")
        logger.info("\n".join(tle))
        return tle

    def calibrate(self) -> None:
        if not self.owmid:
            # From the ephem docs, temperature defaults to 25 C, pressure defaults to 1010 mBar
            logger.info("not fetching weather for calibration")
            return
        r = requests.get(
            f"https://api.openweathermap.org/data/3.0/onecall?lat={deg(self.obs.lat):.3f}&lon="
            f"{deg(self.obs.lon):.3f}&exclude=minutely,hourly,daily,alerts&units=metric&appid="
            f"{self.owmid}",
            timeout=10,
        )
        c = r.json()["current"]
        self.obs.temp = c["temp"]
        self.obs.pressure = c["pressure"]

    def now(self) -> ephem.Date:
        '''ephem.now() does not provide subsecond precision, use this instead.'''
        return ephem.Date(datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))

    def freshen(self, date: ephem.Date | None = None) -> Tracker:
        """Perform a new calculation of satellite relative to observer."""
        self.obs.date = date or self.now()
        self.sat.compute(self.obs)
        return self

    def azel(self) -> AzEl:
        """Return the current track azimuth and elevation in radians."""
        return AzEl(self.sat.az, self.sat.alt)

    @property
    def doppler(self) -> float:
        """Returns the unitless value to scale frequencies for doppler shift.

        Note that as the satellite is approaching the observer the value is negative, and as it's
        moving away the value is positive.
        """
        # both values should be float but ephem lacks type annotations.
        return float(self.sat.range_velocity / ephem.c)

    def next_pass_after(self, date: ephem.Date, *, singlepass: bool = True) -> PassInfo:
        self.obs.date = date
        info = self.obs.next_pass(self.sat, singlepass)

        self.obs.date = info[2]  # max el time
        self.sat.compute(self.obs)

        return PassInfo(info[0], info[1], info[2], info[3], info[4], info[5], self.sat.az)

    def get_next_pass(self, min_el: float = 15.0, max_lookahead: int = 100) -> PassInfo:
        np = self.next_pass_after(ephem.now())
        fails = 0
        while deg(np.maximum_altitude) < min_el and fails < max_lookahead:
            fails += 1
            np = self.next_pass_after(np.set_time)
        if fails >= max_lookahead:
            logger.info(
                "The TLE or station location is fishy. Unable to find a pass with elevation >%f°",
                min_el,
            )
        return np

    def sleep_until_next_pass(self, min_el: float = 15.0) -> PassInfo:
        np = self.next_pass_after(ephem.now(), singlepass=False)
        if np.rise_time > np.set_time and self.obs.date < np.maximum_altitude_time:
            # FIXME we could use np.maximum_altitude_time instead of np.set_time to see if we are
            # in the first half of the pass
            logger.info("In a pass now!")
            return self.next_pass_after(ephem.Date(self.obs.date - (30 * ephem.minute)))
        np = self.next_pass_after(ephem.now())
        while deg(np.maximum_altitude) < min_el:
            np = self.next_pass_after(np.set_time)
        seconds = (np.rise_time - ephem.now()) / ephem.second
        logger.info(
            "Sleeping %s until next rise time %s for a %.2f°el pass.",
            timedelta(seconds=seconds),
            ephem.localtime(np.rise_time),
            deg(np.maximum_altitude),
        )
        sleep(seconds)
        if ephem.now() - self.sat.epoch > 1:
            self.sat = ephem.readtle(*self.fetch_tle())
        return np
