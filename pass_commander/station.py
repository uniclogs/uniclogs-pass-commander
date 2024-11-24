import logging
import re
import socket
from time import sleep

logger = logging.getLogger(__name__)


class Station:
    def __init__(self, host: str, station_port: int = 5005, band: str = "l-band"):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.connect((host, station_port))
        self.band = band

    def _command(self, verb: str) -> str:
        if re.match(
            r"^(gettemp|((l-band|uhf) (pa-power|rf-ptt)|rotator) (on|off|status))$",
            verb,
        ):
            logger.info("Sending command: %s", verb)
            self.s.send(verb.encode())
            return self._response()
        else:
            logger.warning("invalid command: %s", verb)
            return ''

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
        elif m := re.search(r"Please wait (\S+) seconds", ret):
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

    def gettemp(self) -> float:
        ret = self._command("gettemp")
        return float(ret[6:].strip())

    def close(self) -> None:
        self.s.close()
