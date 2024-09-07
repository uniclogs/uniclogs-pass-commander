#!/usr/bin/env python3
#
# Copyright (c) 2022-2023 Kenny M.
#
# This file is part of UniClOGS Pass Commander
# (see https://github.com/uniclogs/uniclogs-pass_commander).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#


import os
import re
import requests
from datetime import datetime, timedelta
from math import degrees as deg
from multiprocessing import Manager
from time import sleep
from typing import Optional
import ephem


class Tracker:
    def __init__(
        self, observer, sat_id="OreSat0", local_only=False, tle_cache=None, owmid=None
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
        self.sat = None
        self.update_tle()
        self.share = Manager().dict()
        self.share["target_el"] = 90

    def fetch_tle(self):
        if self.local_only and self.tle_cache and self.sat_id in self.tle_cache:
            print("using cached TLE")
            tle = self.tle_cache[self.sat_id]
        elif self.local_only and self.query == "CATNR":
            fname = f'{os.environ["HOME"]}/.config/Gpredict/satdata/{self.sat_id}.sat'
            if os.path.isfile(fname):
                print("using Gpredict's cached TLE")
                with open(fname) as file:
                    lines = file.readlines()[3:6]
                    tle = [line.rstrip().split("=")[1] for line in lines]
        else:
            tle = requests.get(
                f"https://celestrak.org/NORAD/elements/gp.php?{self.query}={self.sat_id}"
            ).text.splitlines()
            if tle[0] == "No GP data found":
                if self.tle_cache and self.sat_id in self.tle_cache:
                    print(f"No results for {self.sat_id} at celestrak, using cached TLE")
                    tle = self.tle_cache[self.sat_id]
                else:
                    raise ValueError(f"Invalid satellite identifier: {self.sat_id}")
        print("\n".join(tle))
        return tle

    def update_tle(self):
        self.sat = ephem.readtle(*self.fetch_tle())

    def calibrate(self):
        if self.local_only:
            print("not fetching weather for calibration")
            return
        if not self.owmid:
            raise ValueError("missing OpenWeatherMap API key")
        r = requests.get(
            f"https://api.openweathermap.org/data/2.5/onecall?lat={deg(self.obs.lat):.3f}&lon="
            f"{deg(self.obs.lon):.3f}&exclude=minutely,hourly,daily,alerts&units=metric&appid={self.owmid}"
        )
        c = r.json()["current"]
        self.obs.temp = c["temp"]
        self.obs.pressure = c["pressure"]

    def freshen(self, date: Optional[ephem.Date]=None):
        """perform a new calculation of satellite relative to observer"""
        # ephem.now() does not provide subsecond precision, use ephem.Date() instead:
        self.obs.date = date or ephem.Date(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"))
        # self.obs.date = ephem.Date(self.obs.date + ephem.second)   # look-ahead
        self.sat.compute(self.obs)
        return self

    def azel(self):
        """returns a tuple containing azimuth and elevation in degrees"""
        self.share["target_el"] = deg(self.sat.alt)
        return (self.sat.az, self.sat.alt)

    @property
    def doppler(self):
        """returns the unitless value to scale frequencies for doppler shift

        Note that as the satellite is approaching the observer the value is negative, and as it's
        moving away the value is positive.
        """
        return self.sat.range_velocity / ephem.c

    def az_at_time(self, time):
        self.obs.date = time
        self.sat.compute(self.obs)
        return self.sat.az

    def get_next_pass(self, min_el=15):
        self.obs.date = ephem.now()
        np = self.obs.next_pass(self.sat)
        fails = 0
        while deg(np[3]) < min_el and fails < 100:
            fails += 1
            self.obs.date = np[4]
            np = self.obs.next_pass(self.sat)
        if fails >= 100:
            print(f"Something about the TLE or station location is fishy. Unable to find a pass with elevation >{min_el}°")
        return np

    def sleep_until_next_pass(self, min_el=15):
        self.obs.date = ephem.now()
        np = self.obs.next_pass(self.sat, singlepass=False)
        # print(self.obs.date, str(np[0]), deg(np[1]), str(np[2]), deg(np[3]), str(np[4]), deg(np[5]))
        if np[0] > np[4] and self.obs.date < np[2]:
            # FIXME we could use np[2] instead of np[4] to see if we are in the first half of the pass
            print("In a pass now!")
            self.obs.date = ephem.Date(self.obs.date - (30 * ephem.minute))
            np = self.obs.next_pass(self.sat)
            return np
        np = self.obs.next_pass(self.sat)
        while deg(np[3]) < min_el:
            self.obs.date = np[4]
            np = self.obs.next_pass(self.sat)
        seconds = (np[0] - ephem.now()) / ephem.second
        print(
            f"Sleeping {timedelta(seconds=seconds)} until next rise time {ephem.localtime(np[0])} for a {deg(np[3]):.2f}°el pass."
        )
        # print("Sleeping %.3f seconds until next rise time %s for a %.2f°el pass." % (seconds, ephem.localtime(np[0]), deg(np[3])))
        # print(str(np[0]), deg(np[1]), str(np[2]), deg(np[3]), str(np[4]), deg(np[5]))
        sleep(seconds)
        if ephem.now() - self.sat.epoch > 1:
            self.update_tle()
        return np
        """
        0  Rise time
        1  Rise azimuth
        2  Maximum altitude time
        3  Maximum altitude
        4  Set time
        5  Set azimuth
        """
