from multiprocessing import Manager

import Hamlib


class Rotator:
    def __init__(self, host, port=4533, az_cal=0, el_cal=0, local_only=False):
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

    def go(self, az, el, no_rot, local_only=False):
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
        (now_az,
         now_el) = self.r.get_position()  # This consistently returns the last requested az/el, not present location
        (now_az, now_el) = self.r.get_position()  # Second request gives us the actual present location - why?
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
            # print('Moving! from \t\t\t% 3.3f°az % 3.3f°el to % 3.3f°az % 3.3f°el' % (now_az, now_el, az, el))
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
        self.go(180, 90)
