import re
import socket
from time import sleep


class Station:
    def __init__(self, host, station_port=5005, band='l-band'):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = (host, station_port)
        self.band = band

    def command(self, verb, no_tx):
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
