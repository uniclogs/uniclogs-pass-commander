#!/usr/bin/env python3

import logging
import os
import selectors
import socket
from threading import Thread

logger = logging.getLogger(__name__)


class Stationd(Thread):
    def __init__(self, addr: tuple[str, int] | None = None, temperature: float = 25.0) -> None:
        '''Thread that locally simulates stationd for testing.

        Parameters
        ----------
        addr
            IP and port to listen with, usually localhost or some loopback
        temperature
            The default temperature to return from gettemp. Can be changed at runtime via
            self.temperature
        '''
        super().__init__(name=self.__class__.__name__, daemon=True)
        if addr is None:
            addr = ('127.0.0.1', 0)
        self._s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        self._s.bind(addr)
        self._addr: tuple[str, int] = self._s.getsockname()
        self._r, self._w = os.pipe2(os.O_NONBLOCK)
        self.temperature = temperature

    @property
    def addr(self) -> tuple[str, int]:
        return self._addr

    def _action(self, action: str) -> str:
        # The stationd protocol is more complex than I actually want to try to emulate.
        # This is mostly nonsense returns but class Station seems to accept them without
        # crashing.
        words = action.split()
        if len(words) == 1 and words[0] == 'gettemp':
            return f"temp: {self.temperature}"
        if len(words) == 3:
            if words[0] not in self.state:
                return 'FAIL: Invalid Command'
            if words[1] not in self.state[words[0]]:
                return 'FAIL: Invalid Command'

            # Error if ptt is on and
            #  - turning PA off
            #  - turning LNA on
            if words[1] == 'pa-power' and words[2] == 'off' and self.state[words[0]]['rf-ptt']:
                return f'FAIL: {action} PTT Conflict'
            if words[1] == 'lna' and words[2] == 'on' and self.state[words[0]]['rf-ptt']:
                return f'FAIL: {action} PTT Conflict'

            match words[2]:
                case 'on':
                    self.state[words[0]][words[1]] = True
                    return f'SUCCESS: {action}'
                case 'off':
                    self.state[words[0]][words[1]] = False
                    return f'SUCCESS: {action}'
                case 'status':
                    return f'{action} {"ON" if self.state[words[0]][words[1]] else "OFF"}'
                case _:
                    return 'FAIL: Invalid Command'
        return 'FAIL: Invalid Command'

    def _respond(self) -> bool:
        packet, addr = self._s.recvfrom(4096)
        action = packet.decode('ascii')
        logger.info("%s %s", addr, action)
        self._s.sendto(self._action(action).encode('ascii'), addr)
        return False

    def run(self) -> None:
        sel = selectors.DefaultSelector()
        sel.register(self._s, selectors.EVENT_READ, self._respond)
        sel.register(self._r, selectors.EVENT_READ, lambda: True)

        self.state = {
            'l-band': {
                'rf-ptt': False,
                'pa-power': False,
                'lna': False,
            },
            'uhf': {
                'rf-ptt': False,
                'pa-power': False,
                'lna': False,
            },
        }

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
