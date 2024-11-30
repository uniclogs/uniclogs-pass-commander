#!/usr/bin/env python3
"""Tiny testing script to send ascii hex bytes from stdin to the Pass Commander EDL socket"""

import socket
from argparse import ArgumentParser
from contextlib import suppress
from time import sleep


def main() -> None:
    parser = ArgumentParser("Send ascii hex from stdin to the EDL socket")
    parser.add_argument(
        "-p",
        "--port",
        default=10025,
        type=int,
        help="port to use for the uplink, default is %(default)s",
    )
    args = parser.parse_args()

    packet = bytes.fromhex(input())

    edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    edl.connect(("127.0.0.1", args.port))

    while True:
        print("<--", packet.hex())
        edl.send(packet)
        sleep(1)


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        main()
