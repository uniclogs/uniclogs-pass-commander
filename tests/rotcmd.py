#!/usr/bin/env python3

import argparse
import select
from cmd import Cmd
from pathlib import Path
from threading import Thread
from typing import Never

from pass_commander.config import AzEl
from pass_commander.rotator import Rotator


class RotCmd(Cmd):
    def __init__(self, rot: Rotator) -> None:
        '''Small cmdline to interact with a rotator.'''
        super().__init__()
        self.rot = rot
        Thread(target=self._listen, daemon=True).start()

    def _listen(self) -> Never:
        epoll = select.epoll()
        epoll.register(self.rot.listener, select.EPOLLIN)
        while True:
            for _ in epoll.poll(-1):
                print(f'\n{self.rot.event()}\n{self.prompt}', end='')

    def do_limits(self, _arg: str) -> None:
        print(*self.rot.limits())

    def do_go(self, arg: str) -> None:
        az, el = arg.split()
        pos = AzEl(float(az), float(el))
        self.rot.go(pos)
        self.rot.start_polling(pos)

    def do_pos(self, _arg: str) -> None:
        print(self.rot.position())

    def do_park(self, _arg: str) -> None:
        self.rot.park()
        self.rot.start_polling(AzEl(180, 90))

    def do_ppd(self, _arg: str) -> None:
        print(self.rot.ppd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path, help='rotator /dev path')
    args = parser.parse_args()

    rot = Rotator(args.path)
    try:
        RotCmd(rot).cmdloop()
    finally:
        rot.close()
