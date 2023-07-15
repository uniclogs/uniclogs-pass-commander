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

'''
  Todo:
    - parse paramaters for testing
      - without hardware
      - low-gain TX
    - verify doppler
    - add a mode for decoding arbitrary sats, then test
'''

from xmlrpc.client import ServerProxy
from time import sleep
from datetime import datetime, timedelta
import ephem
from math import sin, cos, degrees as deg, radians as rad
import requests
import Hamlib
import socket
from apscheduler.schedulers.background import BackgroundScheduler
from multiprocessing import Manager
from threading import Lock
import sys
import re
import os
import pydbus
import logging as log
import configparser

# Config File
config_file = os.path.expanduser('~/.config/OreSat/pass_commander.ini')
config = configparser.ConfigParser()
if not len(config.read(config_file)):
    print('Config file seems to be missing. Initializing.')
    os.makedirs(os.path.dirname(config_file))
    with open(config_file, 'w') as f:
        f.write('''[Main]
owmid = <open weather map API key>
edl = <EDL command to send>
txgain = 47

[Hosts]
radio = 127.0.0.2
station = 127.0.0.1
rotator = 127.0.0.1

[Observer]
lat = <latitude in decimal notation>
lon = <longitude in decimal notation>
alt = <altitude in meters>
name = <station name or callsign>
''')
    print(f'Please edit {config_file} before running again.')
    sys.exit(1)

# This is just shoehorned in here and ugly. Please fix!
def confget(conf, tree):
    if tree[0] in conf:
        if len(tree) == 1:
            return conf[tree[0]]
        else:
            return confget(conf[tree[0]], tree[1:])
    else:
        print(f'Configuration element missing: {tree[0]}')
        sys.exit(2)


host_radio = confget(config, ['Hosts', 'radio'])
host_station = confget(config, ['Hosts', 'station'])
host_rotator = confget(config, ['Hosts', 'rotator'])
observer = [
        confget(config, ['Observer', 'lat']),
        confget(config, ['Observer', 'lon']),
        int(confget(config, ['Observer', 'alt']))
    ]
# sat_id can be International Designator, Catalog Number, or Name
sat_id = 'OreSat0'
pass_count = 9999 # Maximum number of passes to operate before shutting down
if len(sys.argv) > 1:
    if re.match(r'\d{1,2}$', sys.argv[1]):
        pass_count = int(sys.argv[1])
    else:
        sat_id = sys.argv[1]
az_cal, el_cal = 0, 0
owmid = confget(config, ['Main', 'owmid'])
edl_packet = confget(config, ['Main', 'edl'])
local_only=False
no_tx=False
no_rot=False

tx_gain = int(confget(config, ['Main', 'txgain']))

# XXX These should be set by command line arguments
#local_only=True # XXX Test mode with no connections
#no_tx=True  # XXX
#no_rot=True  # XXX

tle_cache = {
        'OreSat0': ['ORESAT0', '1 52017U 22026K   23092.57919752  .00024279  00000+0  10547-2 0  9990', '2 52017  97.5109  94.8899 0023022 355.7525   4.3512 15.22051679 58035'],
        '2022-026K': ['ORESAT0', '1 52017U 22026K   23092.57919752  .00024279  00000+0  10547-2 0  9990', '2 52017  97.5109  94.8899 0023022 355.7525   4.3512 15.22051679 58035'],
        'end': True
        }

log.basicConfig()
log.getLogger('apscheduler').setLevel(log.ERROR)

class Rotator:
    def __init__(self, host, port=4533, az_cal=0, el_cal=0):
        Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE)
        self.r = Hamlib.Rot(Hamlib.ROT_MODEL_NETROTCTL)
        self.r.set_conf('rot_pathname', f'{host}:{port}')
        self.share = Manager().dict()
        self.share['moving'] = False
        if not local_only:
            self.r.open()
            self.r.state.az_offset = az_cal
            self.r.state.el_offset = el_cal
            self.amin_az = self.r.state.min_az - az_cal
            self.amax_az = self.r.state.max_az - az_cal
            self.amin_el = self.r.state.min_el - el_cal
            self.amax_el = self.r.state.max_el - el_cal
            self.last_reported_az = -1
            self.last_reported_el = -1

    def get_el(self):
        return self.r.get_position()[1]

    def go(self, az, el):
        if local_only or no_rot:
            print(f'Not going to {az: >7.3f}°az {el: >7.3f}°el')
            return
        if az < self.amin_az:
            az = self.amin_az
        if az > self.amax_az:
            az = self.amax_az
        if el < self.amin_el:
            el = self.amin_el
        if el > self.amax_el:
            el = self.amax_el
        (now_az, now_el) = self.r.get_position() # This consistently returns the last requested az/el, not present location
        (now_az, now_el) = self.r.get_position() # Second request gives us the actual present location - why?
        if self.r.error_status:
            print(f'Rotator controller daemon rotctld is returning error {self.r.error_status}')
            self.share['moving'] = self.r.error_status
            self.r.close()
            self.r.open()
            if self.r.error_status:
                print(f'rotctld is returning error {self.r.error_status} from reconnect attempt')
                # FIXME Figure out a thread-safe way to rais an error and abort this pass. Maybe send an alert, too?
                return
            else:
                print(f'Rotator controller reconnected')
                return self.go(az, el)
        elif self.share['moving'] == True and now_az == self.last_reported_az and now_el == self.last_reported_el:
            print(f'Rotator movement failed')
            self.share['moving'] = 'Failed'
            # FIXME Figure out a thread-safe way to rais an error and abort this pass. Maybe send an alert, too?
        elif abs(az - now_az) > 5 or abs(el - now_el) > 3:
            #print('Moving! from \t\t\t% 3.3f°az % 3.3f°el to % 3.3f°az % 3.3f°el' % (now_az, now_el, az, el))
            print(f'{"Moving from": <28}{now_az: >7.3f}°az {now_el: >7.3f}°el to {az: >7.3f}°az {el: >7.3f}°el')
            self.share['moving'] = True
            self.r.set_position(az, el)
            self.last_requested_az = az
            self.last_requested_el = el
            self.last_reported_az = now_az
            self.last_reported_el = now_el
        else:
            self.share['moving'] = False

    def park(self):
        self.go(180,90)


class Navigator:
    ''' satellite passes don't care about our rotator end-stops -- find a workaround '''
    def __init__(self, track, rise_time, rise_az, maxel_time, max_elevation, set_time, set_az):
        self.track = track
        self.rise_time = rise_time
        self.rise_az = rise_az
        self.maxel_time = maxel_time
        self.max_elevation = max_elevation
        self.set_time = set_time
        self.set_az = set_az

        self.maxel_az = self.track.az_at_time(maxel_time)
        z = (abs(rise_az - self.maxel_az) + abs(self.maxel_az - set_az)) > (1.5*ephem.pi)
        if self.no_zero_cross(rise_az, self.maxel_az, set_az):
            self.nav_mode = self.nav_straight
        elif self.no_zero_cross(*self.rot_pi((rise_az, self.maxel_az, set_az))):
            self.nav_mode = self.nav_backhand
        else:
            self.nav_mode = self.nav_straight    # FIXME
            ''' This probably means we need to extend into the 450° operating area '''
        #print('rise:%s rise:%.3f°az maxel:%s max:%.3f°el set:%s set:%.3f°az'%(rise_time, deg(rise_az), maxel_time, deg(max_elevation), set_time, deg(set_az)))
        print(f'rise:{rise_time} rise:{deg(rise_az):.3f}°az maxel:{maxel_time} '
              f'max:{deg(max_elevation):.3f}°el set:{set_time} set:{deg(set_az):.3f}°az')
        if deg(max_elevation) >= 78:
            self.flip_az = (self.rise_az-((self.rise_az-self.set_az)/2)+ephem.pi/2)%(2*ephem.pi)
            if self.az_n_hem(self.flip_az):
                self.flip_az = self.rot_pi(self.flip_az)
            self.nav_mode = self.nav_flip
            print(f'Flip at {deg(self.flip_az):.3f}')
        #print('Zero_cross:%r mode:%s start:%s rise:%.3f°az peak:%.3f°az set:%.3f°az' %
        #        (z, self.nav_mode.__name__, rise_time, deg(rise_az), deg(self.maxel_az), deg(set_az)))
        print(f'Zero_cross:{z} mode:{self.nav_mode.__name__} start:{rise_time} '
              f'rise:{deg(rise_az):.3f}°az peak:{deg(self.maxel_az):.3f}°az set:{deg(set_az):.3f}°az')

    def rot_pi(self, rad):
        ''' rotate any radian by half a circle '''
        if type(rad) == tuple:
            return tuple([(x+ephem.pi)%(2*ephem.pi) for x in rad])
        return (rad+ephem.pi)%(2*ephem.pi) 
    
    def no_zero_cross(self, a, b, c):
        return (a < b < c) or (a > b > c)

    def az_e_hem(self, az):
        return az<ephem.pi

    def az_n_hem(self, az):
        return cos(az) > 0

    def nav_straight(self, azel):
        return azel

    def nav_backhand(self, azel):
        (input_az, input_el) = azel
        return ((input_az+ephem.pi)%(2*ephem.pi), ephem.pi-input_el)

    def nav_flip(self, azel):
        (input_az, input_el) = azel
        flip_el = ephem.pi/2 - (cos(input_az-self.flip_az) * (ephem.pi/2-input_el))
        return (self.flip_az, flip_el)

    def azel(self, azel):
        navazel = self.nav_mode(azel)
        #print('Navigation corrected from \t% 3.3f°az % 3.3f°el to % 3.3f°az % 3.3f°el' % tuple(deg(x) for x in (*azel, *navazel)))
        print(f'{"Navigation corrected from": <28}{deg(azel[0]): >7.3f}°az {deg(azel[1]): >7.3f}°el to {deg(navazel[0]): >7.3f}°az {deg(navazel[1]): >7.3f}°el')
        return navazel


class Tracker:
    def __init__(self, observer, sat_id=sat_id):
        self.sat_id = sat_id
        m = re.match(r'(?:20)?(\d\d)-?(\d{3}[A-Z])$', self.sat_id.upper())
        if m:
            self.sat_id = '20%s-%s'%m.groups()
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
        
    def fetch_tle(self):
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
            tle = requests.get(f'https://celestrak.org/NORAD/elements/gp.php?{self.query}={self.sat_id}').text.splitlines()
            if tle[0] == 'No GP data found':
                raise ValueError(f'Invalid satellite identifier: {self.sat_id}')
        print('\n'.join(tle))
        return tle

    def update_tle(self):
        self.sat = ephem.readtle(*self.fetch_tle())

    def calibrate(self):
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
        #self.obs.date = ephem.Date(self.obs.date + ephem.second)   # look-ahead
        self.sat.compute(self.obs)
        return self

    def azel(self):
        ''' returns a tuple containing azimuth and elevation in degrees '''
        self.share['target_el'] = deg(self.sat.alt)
        return(self.sat.az, self.sat.alt)

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

    def sleep_until_next_pass(self, min_el=15):
        self.obs.date = ephem.now()
        np = self.obs.next_pass(self.sat, singlepass=False)
        #print(self.obs.date, str(np[0]), deg(np[1]), str(np[2]), deg(np[3]), str(np[4]), deg(np[5]))
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
        seconds = (np[0]-ephem.now())/ephem.second
        print(f'Sleeping {timedelta(seconds=seconds)} until next rise time {ephem.localtime(np[0])} for a {deg(np[3]):.2f}°el pass.')
        #print("Sleeping %.3f seconds until next rise time %s for a %.2f°el pass." % (seconds, ephem.localtime(np[0]), deg(np[3])))
        #print(str(np[0]), deg(np[1]), str(np[2]), deg(np[3]), str(np[4]), deg(np[5]))
        sleep(seconds)
        if ephem.now() - self.sat.epoch > 1:
            self.update_tle()
        return np
        '''
        0  Rise time
        1  Rise azimuth
        2  Maximum altitude time
        3  Maximum altitude
        4  Set time
        5  Set azimuth
        '''


class Radio:
    def __init__(self, host, xml_port=10080, edl_port=10025):
        self.edl_addr = (host, edl_port)
        self.xml_addr = (host, xml_port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.lock = Lock()
        self.xo = ServerProxy('http://%s:%i' % self.xml_addr)
        if not local_only:
            self.txfreq = self.xo.get_tx_center_frequency()
            self.rxfreq = self.xo.get_rx_target_frequency()

    def ident(self):
        old_selector = self.xo.get_tx_selector()
        self.xo.set_tx_selector('morse')
        self.xo.set_morse_bump(self.xo.get_morse_bump()^1)
        sleep(4)
        self.xo.set_tx_selector(old_selector)
        return self.xo

    def command(self, func, *args):
        with self.lock:
            # With the locking, a shared ServerProxy object should be fine, but no.
            xo = ServerProxy('http://%s:%i' % self.xml_addr)
            ret = xo.__getattr__(func)(*args)
        return ret

    def edl(self, packet):
        self.s.sendto(packet, self.edl_addr)


class Station:
    def __init__(self, host, station_port=5005, band='l-band'):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = (host, station_port)
        self.band = band

    def command(self, verb):
        if no_tx and re.search(r'pa-power', verb):
            print('Not sending command: ', verb)
            return
        if re.match(r'^(gettemp|((l-band|uhf) (pa-power|rf-ptt)|rotator) (on|off|status))$', verb):
            print(f'Sending command: {verb}')
            self.s.sendto((verb).encode(), self.addr)
            return self.response()

    def commands(self, *verbs):
        for v in verbs:
            ret = self.command(v)
            sleep(.1)
        return ret

    def response(self):
        data, addr = self.s.recvfrom(4096)
        stat = data.decode().strip()
        print(f'StationD response: {stat}')
        return stat

    def pa_on(self):
        self.command(f'{self.band} pa-power on')
        return self.command(f'{self.band} pa-power on')

    def pa_off(self):
        ret = self.command(f'{self.band} pa-power off')
        if re.search(r'PTT Conflict', ret):
            self.pa_off()
            sleep(120)
            return self.pa_off()
        elif m := re.search(r'Please wait (\S+) seconds', ret):
            sleep(int(m.group(1)))
            return self.pa_off()
        return ret

    def ptt_on(self):
        ret = self.command(f'{self.band} rf-ptt on')
        # FIXME TIMING: wait for PTT to open (100ms is just a guess)
        sleep(.1)
        return ret

    def ptt_off(self):
        return self.command(f'{self.band} rf-ptt off')

    def gettemp(self):
        ret = self.command('gettemp')
        return float(ret[6:].strip())


class Main:
    def __init__(self,
            o_tracker=Tracker(observer, sat_id=sat_id),
            o_rotator=Rotator(host_rotator, az_cal=az_cal, el_cal=el_cal),
            o_radio=Radio(host_radio),
            o_station=Station(host_station),
            o_scheduler=BackgroundScheduler()):
        self.track = o_tracker
        self.rot = o_rotator
        self.rad = o_radio
        self.sta = o_station
        self.scheduler = o_scheduler
        self.scheduler.start()
        self.nav = None

    def NTPSynchronized(self):
        return pydbus.SystemBus().get(".timedate1").NTPSynchronized

    def require_clock_sync(self):
        while not self.NTPSynchronized():
            print('System clock is not synchronized. Sleeping 60 seconds.')
            sleep(60)
        print('System clock is synchronized.')

    def edl(self, packet):
        self.rad.command('set_gpredict_tx_frequency', self.rad.txfreq - self.track.freshen().doppler(self.rad.txfreq))
        self.rad.edl(packet)

    def autorun(self, count=9999):
        print(f'Running for {count} passes')
        while count > 0:
            self.require_clock_sync()
            np = self.track.sleep_until_next_pass()
            self.nav = Navigator(self.track, *np)
            self.work_pass()
            seconds = (np[4]-ephem.now()) / ephem.second + 1
            if seconds > 0:
                print(f'Sleeping {seconds:.3f} seconds until pass is really over.')
                sleep(seconds)
            count -= 1

    def work_pass(self, packet=edl_packet):
        if local_only:
            return self.test_bg_rotator()
        degc = self.sta.gettemp()
        if degc > 30:
            print(f'Temperature is too high ({degc}°C). Skipping this pass.')
            sleep(1)
            return
        self.packet = bytes.fromhex(packet)
        print('Packet to send: ', self.packet)
        self.track.calibrate()
        print('Adjusted for temp/pressure')
        self.scheduler.add_job(self.update_rotator, 'interval', seconds=.5)
        print('Scheduled rotator')
        self.rad.command('set_tx_selector', 'edl')
        print('Selected EDL TX')
        self.rad.command('set_tx_gain', tx_gain)
        print('Set TX gain')
        sleep(2)
        print('Rotator should be moving by now')
        while self.rot.share['moving'] == True:
            sleep(.1)
        if self.rot.share['moving']:
            print('Rotator communication anomaly detected. Skipping this pass.')
            self.scheduler.remove_all_jobs()
            sleep(1)
            return
        print('Stopped moving')
        self.sta.pa_on()
        print('Station amps on')
        sleep(.2)
        self.sta.ptt_on()
        print('Station PTT on')
        self.rad.ident()
        print('Sent Morse ident')
        self.sta.ptt_off()
        print('Station PTT off')
        print('Waiting for bird to reach 10°el')
        while self.track.share['target_el'] < 10:
            sleep(.1)
        print('Bird above 10°el')
        while self.track.share['target_el'] >= 10:
            self.sta.ptt_on()
            print('Station PTT on')
            self.edl(self.packet)
            print('Sent EDL')
            # FIXME TIMING: wait for edl to finish sending
            sleep(.5)
            self.sta.ptt_off()
            print('Station PTT off')
            sleep(3.5)
        self.scheduler.remove_all_jobs()
        print('Removed scheduler jobs')
        self.sta.ptt_on()
        print('Station PTT on')
        self.rad.ident()
        print('Sent Morse ident')
        self.sta.ptt_off()
        print('Station PTT off')
        self.rad.command('set_tx_gain', 3)
        print('Set TX gain to min')
        self.rot.park()
        print('Parked rotator')
        print('Waiting for PA to cool')
        sleep(120)
        self.sta.pa_off()
        print('Station shutdown TX amp')

    def update_rotator(self):
        azel = self.nav.azel(self.track.freshen().azel())
        if not local_only:
            self.rot.go(*tuple(deg(x) for x in azel))
            self.rad.command('set_gpredict_rx_frequency', self.track.doppler(self.rad.rxfreq) - self.rad.rxfreq)

    ''' Testing stuff goes below here '''
    def dryrun_time(self):
        self.track.obs.date = self.track.obs.date + (30*ephem.second)
        self.track.sat.compute(self.track.obs)
        azel = self.nav.azel(self.track.azel())

    def dryrun(self):
        np = self.track.get_next_pass(80)
        self.nav = Navigator(self.track, *np)
        self.track.obs.date = np[0]
        self.scheduler.add_job(self.dryrun_time, 'interval', seconds=.2)
        sleep(4.5)
        self.scheduler.remove_all_jobs()

    def test_rotator(self):
        while True:
            print(self.update_rotator())
            sleep(.1)

    def test_bg_rotator(self):
        self.scheduler.add_job(self.update_rotator, 'interval', seconds=.5)
        while True:
            sleep(1000)
            #print(self.rot.share['moving'])

    def test_doppler(self):
        while True:
            print(self.track.freshen().doppler())
            sleep(.1)

    def test_morse(self):
        while True:
            self.rad.ident()
            sleep(30)


class Attic:
    ''' storage for junk that might be useful someday '''
    def conf():
        ''' This will probably never be used '''
        import configparser
        config = configparser.ConfigParser()
        config.read('OreSat0.cfg')
        print(config['main']['rf_samp_rate'])


def main():
    Main().autorun(pass_count)
    # Tests could include things like:
    #Main().dryrun()
    #Main().test_doppler()
    #Main().track.sleep_until_next_pass()

if __name__ == '__main__':
    main()
