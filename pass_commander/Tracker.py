import os
import re
from datetime import datetime, timedelta
from math import degrees as deg
from multiprocessing import Manager
from time import sleep

import ephem
import requests


class Tracker:
    def __init__(self, observer, sat_id):
        self.sat_id = sat_id
        m = re.match(r'(?:20)?(\d\d)-?(\d{3}[A-Z])$', self.sat_id.upper())
        if m:
            self.sat_id = '20%s-%s' % m.groups()
            self.query = 'INTDES'
        elif re.match(r'\d{5}$', self.sat_id):
            self.query = 'CATNR'
        else:
            self.query = 'NAME'
        self.obs = ephem.Observer()
        (self.obs.lat, self.obs.lon, self.obs.elev) = observer
        self.sat = None
        self.update_tle()
        self.share = Manager().dict()
        self.share['target_el'] = 90

    def fetch_tle(self, local_only, tle_cache):
        if local_only and tle_cache and self.sat_id in tle_cache:
            print('using cached TLE')
            tle = tle_cache[self.sat_id]
        elif local_only and self.query == 'CATNR':
            fname = f'{os.environ["HOME"]}/.config/Gpredict/satdata/{self.sat_id}.sat'
            if os.path.isfile(fname):
                print('using Gpredict\'s cached TLE')
                with open(fname) as file:
                    lines = file.readlines()[3:6]
                    tle = [line.rstrip().split('=')[1] for line in lines]
        else:
            tle = requests.get(
                f'https://celestrak.org/NORAD/elements/gp.php?{self.query}={self.sat_id}').text.splitlines()
            if tle[0] == 'No GP data found':
                raise ValueError(f'Invalid satellite identifier: {self.sat_id}')
        print('\n'.join(tle))
        return tle

    def update_tle(self, local_only, tle_cache):
        self.sat = ephem.readtle(*self.fetch_tle(local_only, tle_cache))

    def calibrate(self, local_only, owmid):
        if local_only:
            print('not fetching weather for calibration')
            return
        r = requests.get(f'https://api.openweathermap.org/data/2.5/onecall?lat={deg(self.obs.lat):.3f}&lon='
                         f'{deg(self.obs.lon):.3f}&exclude=minutely,hourly,daily,alerts&units=metric&appid={owmid}')
        c = r.json()['current']
        self.obs.temp = c['temp']
        self.obs.pressure = c['pressure']

    def freshen(self):
        ''' perform a new calculation of satellite relative to observer '''
        # ephem.now() does not provide subsecond precision, use ephem.Date() instead:
        self.obs.date = ephem.Date(datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f'))
        # self.obs.date = ephem.Date(self.obs.date + ephem.second)   # look-ahead
        self.sat.compute(self.obs)
        return self

    def azel(self):
        ''' returns a tuple containing azimuth and elevation in degrees '''
        self.share['target_el'] = deg(self.sat.alt)
        return (self.sat.az, self.sat.alt)

    def doppler(self, freq=436500000):
        ''' returns RX doppler shift in hertz for the provided frequency '''
        return -self.sat.range_velocity / ephem.c * freq

    def az_at_time(self, time):
        self.obs.date = time
        self.sat.compute(self.obs)
        return self.sat.az

    def get_next_pass(self, min_el=15):
        self.obs.date = ephem.now()
        np = self.obs.next_pass(self.sat)
        while deg(np[3]) < min_el:
            self.obs.date = np[4]
            np = self.obs.next_pass(self.sat)
        return np

    def sleep_until_next_pass(self, local_only, tle_cache, min_el=15):
        self.obs.date = ephem.now()
        np = self.obs.next_pass(self.sat, singlepass=False)
        # print(self.obs.date, str(np[0]), deg(np[1]), str(np[2]), deg(np[3]), str(np[4]), deg(np[5]))
        if np[0] > np[4] and self.obs.date < np[2]:
            # FIXME we could use np[2] instead of np[4] to see if we are in the first half of the pass
            print('In a pass now!')
            self.obs.date = ephem.Date(self.obs.date - (30 * ephem.minute))
            np = self.obs.next_pass(self.sat)
            return np
        np = self.obs.next_pass(self.sat)
        while deg(np[3]) < min_el:
            self.obs.date = np[4]
            np = self.obs.next_pass(self.sat)
        seconds = (np[0] - ephem.now()) / ephem.second
        print(
            f'Sleeping {timedelta(seconds=seconds)} until next rise time {ephem.localtime(np[0])} for a {deg(np[3]):.2f}°el pass.')
        # print("Sleeping %.3f seconds until next rise time %s for a %.2f°el pass." % (seconds, ephem.localtime(np[0]), deg(np[3])))
        # print(str(np[0]), deg(np[1]), str(np[2]), deg(np[3]), str(np[4]), deg(np[5]))
        sleep(seconds)
        if ephem.now() - self.sat.epoch > 1:
            self.update_tle(local_only, tle_cache)
        return np

        '''
        0  Rise time
        1  Rise azimuth
        2  Maximum altitude time
        3  Maximum altitude
        4  Set time
        5  Set azimuth
        '''
