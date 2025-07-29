#!/usr/bin/env python3

import argparse
import logging
from pathlib import Path
from time import sleep, time

from pass_commander.config import AzEl
from pass_commander.rotator import Rotator

# Assuming ebv1 with the rot2prog/RAS setup. We can only talk to the controlloer once every two
# seconds, and in the 13.8v setup it moves at about 2deg/s.

logging.basicConfig(level=logging.INFO)


def block_until(rot: Rotator, pos: AzEl) -> None:
    '''Block until the rotator reaches the given position.'''
    azel = AzEl(-1, -1)
    while azel != pos:
        sleep(2)
        azel = rot.position()
        print(azel)


def measure(rot: Rotator, start: AzEl, end: AzEl, wait: float = 70.0) -> float:
    '''Measure the time the rotator takes to path from start to end.

    wait should be at least 2 to not talk to the controller too quickly
    '''
    # The hardware set limits are 1deg/179deg
    rot.go(start)
    block_until(rot, start)

    rot.go(end)
    tstart = time()
    sleep(wait)  # should take about 90s so wake up well early and start polling

    azel = rot.position()
    if azel == end:
        raise RuntimeError("Slept too long")

    while azel != end:
        print(azel)
        sleep(2)
        azel = rot.position()
    tend = time()
    return tend - tstart


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path, help='rotator /dev path')
    args = parser.parse_args()

    rot = Rotator(args.path)
    print("Parking")
    rot.park()
    block_until(rot, AzEl(180.0, 90.0))

    print("Starting el measurement")
    t = measure(rot, AzEl(180.0, 1.0), AzEl(180.0, 179.0))
    print("el slew:", (179 - 1) / t, 'deg/s')
    t = measure(rot, AzEl(180.0, 179.0), AzEl(180.0, 1.0))
    print("el slew:", (179 - 1) / t, 'deg/s')

    print("Starting az measurement")
    t = measure(rot, AzEl(180.0, 1.0), AzEl(1.0, 1.0))
    print("az slew @ 1 el:", (180 - 1) / t, 'deg/s')
    t = measure(rot, AzEl(1.0, 1.0), AzEl(180.0, 1.0))
    print("az slew @ 1 el:", (180 - 1) / t, 'deg/s')

    print("Starting az measurement post park")
    t = measure(rot, AzEl(180.0, 90.0), AzEl(1.0, 90.0))
    print("az slew @ 90 el:", (180 - 1) / t, 'deg/s')
    t = measure(rot, AzEl(1.0, 90.0), AzEl(180.0, 90.0))
    print("az slew @ 90 el:", (180 - 1) / t, 'deg/s')

    print("Starting az/el measurement")
    # FIXME: Az and El time should be measured separately since they could have different rates.
    t = measure(rot, AzEl(1.0, 1.0), AzEl(179.0, 179.0))
    print("az/el slew:", (179 - 1) / t, 'deg/s')
    t = measure(rot, AzEl(179.0, 179.0), AzEl(1.0, 1.0))
    print("az/el slew:", (179 - 1) / t, 'deg/s')

    print("Starting polling measurement")
    # See if polling through the entire path slows things down
    t = measure(rot, AzEl(1.0, 1.0), AzEl(1.0, 179.0), wait=2.0)
    print("el slew:", (179 - 1) / t, 'deg/s')
    t = measure(rot, AzEl(1.0, 179.0), AzEl(1.0, 1.0), wait=2.0)
    print("el slew:", (179 - 1) / t, 'deg/s')

    rot.park()
