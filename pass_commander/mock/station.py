#!/usr/bin/env python3

import logging
import socket
from threading import Thread

logger = logging.getLogger(__name__)


class Stationd(Thread):
    def __init__(self, host: str, port: int):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind((host, port))

    def run(self) -> None:
        while True:
            packet, addr = self.s.recvfrom(4096)
            action = packet.decode('ascii')
            logger.info("%s %s", addr, action)
            # The stationd protocol is more complex than I actually want to try to emulate.
            # This is mostly nonsense returns but class Station seems to accept them without
            # crashing.
            if action.startswith('gettemp'):
                self.s.sendto("temp: 25".encode("ascii"), addr)
            else:
                self.s.sendto(f"SUCCESS: {action}".encode("ascii"), addr)

    def close(self) -> None:
        self.s.close()

if __name__ == "__main__":
    Stationd("127.0.0.2", 5005).start()
