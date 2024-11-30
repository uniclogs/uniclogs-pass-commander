from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import degrees as deg
from time import sleep
from typing import Optional

import ephem
import requests

from .config import AzEl, TleCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PassInfo:
    "https://rhodesmill.org/pyephem/quick.html#transit-rising-and-setting"
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
        local_only: bool = False,
        tle_cache: Optional[TleCache] = None,
        owmid: str = '',
    ):
        self.sat_id = sat_id
        self.local_only = local_only
        self.tle_cache = tle_cache
        self.owmid = owmid
        m = re.match(r"(?:20)?(\d\d)-?(\d{3}[A-Z])$", self.sat_id.upper())
        if m:
            self.sat_id = "20%s-%s" % m.groups()
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
            fname = f'{os.environ["HOME"]}/.config/Gpredict/satdata/{self.sat_id}.sat'
            if os.path.isfile(fname):
                logger.info("using Gpredict's cached TLE")
                with open(fname, encoding="ascii") as file:
                    lines = file.readlines()[3:6]
                    tle = [line.rstrip().split("=")[1] for line in lines]
        elif self.local_only:
            logger.info("No matching TLE is available locally")
        else:
            tle = requests.get(
                f"https://celestrak.org/NORAD/elements/gp.php?{self.query}={self.sat_id}"
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
            f"{self.owmid}"
        )
        c = r.json()["current"]
        self.obs.temp = c["temp"]
        self.obs.pressure = c["pressure"]

    def freshen(self, date: Optional[ephem.Date] = None) -> Tracker:
        """perform a new calculation of satellite relative to observer"""
        # ephem.now() does not provide subsecond precision, use ephem.Date() instead:
        self.obs.date = date or ephem.Date(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"))
        # self.obs.date = ephem.Date(self.obs.date + ephem.second)   # look-ahead
        self.sat.compute(self.obs)
        return self

    def azel(self) -> AzEl:
        """returns current azimuth and elevation in radians"""
        return AzEl(self.sat.az, self.sat.alt)

    @property
    def doppler(self) -> float:
        """returns the unitless value to scale frequencies for doppler shift

        Note that as the satellite is approaching the observer the value is negative, and as it's
        moving away the value is positive.
        """
        # both values should be float but ephem lacks type annotations.
        return float(self.sat.range_velocity / ephem.c)

    def next_pass_after(self, date: ephem.Date, singlepass: bool = True) -> PassInfo:
        self.obs.date = date
        info = self.obs.next_pass(self.sat, singlepass)

        self.obs.date = info[2]  # max el time
        self.sat.compute(self.obs)

        return PassInfo(info[0], info[1], info[2], info[3], info[4], info[5], self.sat.az)

    def get_next_pass(self, min_el: float = 15.0) -> PassInfo:
        np = self.next_pass_after(ephem.now())
        fails = 0
        while deg(np.maximum_altitude) < min_el and fails < 100:
            fails += 1
            np = self.next_pass_after(np.set_time)
        if fails >= 100:
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
