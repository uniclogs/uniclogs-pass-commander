#!/usr/bin/env python3

import logging
import os
import selectors
import socket
from threading import Thread

logger = logging.getLogger(__name__)


class Stationd(Thread):
    def __init__(self, addr: tuple[str, int]) -> None:
        '''Thread that locally simulates stationd for testing.

        Parameters
        ----------
        addr
            IP and port to listen with, usually localhost or some loopback
        '''
        super().__init__(name=self.__class__.__name__, daemon=True)
        self._addr = addr
        self._s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        self._s.bind(addr)
        self._r, self._w = os.pipe2(os.O_NONBLOCK)

    @property
    def addr(self) -> tuple[str, int]:
        return self._addr

    def _respond(self) -> bool:
        packet, addr = self._s.recvfrom(4096)
        action = packet.decode('ascii')
        logger.info("%s %s", addr, action)
        # The stationd protocol is more complex than I actually want to try to emulate.
        # This is mostly nonsense returns but class Station seems to accept them without
        # crashing.
        if action.startswith('gettemp'):
            self._s.sendto("temp: 25".encode("ascii"), addr)
        else:
            self._s.sendto(f"SUCCESS: {action}".encode("ascii"), addr)
        return False

    def run(self) -> None:
        sel = selectors.DefaultSelector()
        sel.register(self._s, selectors.EVENT_READ, self._respond)
        sel.register(self._r, selectors.EVENT_READ, lambda: True)

        stop = False
        while not stop:
            for key, _ in sel.select():
                if stop := key.data():
                    break

        sel.close()
        self._s.close()
        os.close(self._r)
        os.close(self._w)
        logger.info("Stopped")

    def close(self) -> None:
        os.write(self._w, b's')


if __name__ == "__main__":
    Stationd(("127.0.0.2", 5005)).start()
