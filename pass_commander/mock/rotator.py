import logging
from ctypes import c_char_p, cdll
from pathlib import PosixPath
from threading import Thread
from typing import Literal

import serial
from rot2prog import ROT2ProgSim


class PtyRotator(ROT2ProgSim):  # type: ignore[misc]
    def __init__(self, pulses_per_degree: Literal[1, 2, 4]) -> None:
        """Create object, open a serial connection, and start the daemon thread to run simulator.

        Args:
            pulses_per_degree (int): Resolution of simulated ROT2Prog controller. Options are 1,
            2, and 4.
        """
        self._log = logging.getLogger(__name__)

        # open serial port
        self._ser = serial.Serial(
            port='/dev/ptmx',
            baudrate=600,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=None,
            # inter_byte_timeout allows continued operation after a bad packet
            inter_byte_timeout=0.1,
        )

        # FIXME: When Python 3.13 is standard, replace with os.{grantpt|unlockpt|ptsname}
        libc = cdll.LoadLibrary("libc.so.6")
        libc.grantpt(self._ser.fd)
        libc.unlockpt(self._ser.fd)
        libc.ptsname.restype = c_char_p
        self._client_path = PosixPath(libc.ptsname(self._ser.fd).decode('utf-'))

        self._pulses_per_degree = int(pulses_per_degree)
        self._log.info('ROT2Prog simulation interface opened on ' + str(self._ser.name))

        # start daemon thread to communicate on serial port
        # FIXME: daemon = True, removed for stop() testing
        Thread(target=self._run).start()

    @property
    def client_path(self) -> PosixPath:
        return self._client_path

    # FIXME: remove when upstream is updated
    def close(self) -> None:
        super().stop()
        self._ser.cancel_read()

    def _run(self) -> None:
        # Because upstream doesn't handle cancel_read it sometimes OSError: Errno 5
        try:
            super()._run()
        except OSError as e:
            # It's actually a SerialException but it doesn't set errno
            if str(e) != 'read failed: [Errno 5] Input/output error':
                raise
        self._log.info("Stopped")


if __name__ == '__main__':
    from time import sleep

    rot = PtyRotator(1)
    print(rot.client_path)  # noqa: T201
    try:
        while True:
            sleep(100)
    finally:
        rot.close()
