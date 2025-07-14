import logging
import re
import socket
from time import sleep

logger = logging.getLogger(__name__)


class Station:
    def __init__(self, addr: tuple[str, int], band: str = "l-band", lna_delay: float = 1.0) -> None:
        '''Python binding for uniclogs-stationd.

        Yes stationd is written in python but it only exposes a socket interface. Except also
        for reasons this is incomplete and you'll need one instance per band.

        Parameters
        ----------
        addr
            IP address and port of the stationd instance.
        band
            One of `l-band` or `uhf`. We need separate instances to control the radios for each
            band.
        lna_delay
            Time in seconds to wait after toggling the LNA relay. The lna_{on,off} methods toggle
            the relay three times so they'll take 3 * lna_delay seconds.
        '''
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.connect(addr)
        self.band = band
        self.lna_delay = lna_delay

    def _command(self, verb: str) -> str:
        if re.match(
            r"^(gettemp|((l-band|uhf) (pa-power|rf-ptt|lna)|rotator) (on|off|status))$",
            verb,
        ):
            logger.info("Sending command: %s", verb)
            self.s.send(verb.encode())
            return self._response()
        raise ValueError(f"invalid command: {verb}")

    def _response(self) -> str:
        data = self.s.recv(4096)
        stat = data.decode().strip()
        logger.info("StationD response: %s", stat)
        return stat

    def pa_on(self) -> str:
        self._command(f"{self.band} pa-power on")
        return self._command(f"{self.band} pa-power on")

    def pa_off(self) -> str:
        ret = self._command(f"{self.band} pa-power off")
        if re.search(r"PTT Conflict", ret):
            self.pa_off()
            sleep(120)
            return self.pa_off()
        if m := re.search(r"Please wait (\S+) seconds", ret):
            sleep(int(m.group(1)))
            return self.pa_off()
        return ret

    def ptt_on(self) -> str:
        ret = self._command(f"{self.band} rf-ptt on")
        # FIXME TIMING: wait for PTT to open (100ms is just a guess)
        sleep(0.1)
        return ret

    def ptt_off(self) -> str:
        return self._command(f"{self.band} rf-ptt off")

    def lna_on(self) -> str:
        # The LNA Relay is weird, it's not guaranteed to go on on the first try
        # so it must be cycled. From Glenn in oresat-comms, 2024-09-05:
        # Whereas there only needs to be a 100 ms pulse to switch the relay
        # state, I am unsure of how fast the relay can go through multiple
        # state changes. I would suggest as large as one second between
        # commands just to be safe.
        self._command(f"{self.band} lna on")
        sleep(self.lna_delay)
        self._command(f"{self.band} lna off")
        sleep(self.lna_delay)
        ret = self._command(f"{self.band} lna on")
        sleep(self.lna_delay)
        return ret

    def lna_off(self) -> str:
        self._command(f"{self.band} lna off")
        sleep(self.lna_delay)
        self._command(f"{self.band} lna on")
        sleep(self.lna_delay)
        ret = self._command(f"{self.band} lna off")
        sleep(self.lna_delay)
        return ret

    def gettemp(self) -> float:
        ret = self._command("gettemp")
        return float(ret[6:].strip())

    def close(self) -> None:
        self.s.close()
