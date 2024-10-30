#!/usr/bin/env python3

import socket
from argparse import ArgumentParser
from threading import Thread
from xmlrpc.server import SimpleXMLRPCServer


class Edl(Thread):
    def __init__(self, host: str, port: int):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.addr = (host, port)

    def run(self) -> None:
        edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        edl.bind(())
        while True:
            print(edl.recv(4096).hex())


class Flowgraph:
    def __init__(self, host: str, port: int):
        self.morse_bump = 0
        self.tx_selector = "edl"

        self.server = SimpleXMLRPCServer((host, port), allow_none=True, logRequests=False)
        self.server.register_instance(self)

    def start(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        self.server.shutdown()

    def get_tx_center_frequency(self) -> int:
        return 1_265_000_000

    def get_rx_target_frequency(self) -> int:
        return 436_500_000

    def set_gpredict_tx_frequency(self, value: float) -> None:
        print("TX Freq", value)

    def set_gpredict_rx_frequency(self, value: float) -> None:
        print("RX Freq", value)

    def set_morse_bump(self, val: int) -> None:
        self.morse_bump = val
        print("Morse bump", val)

    def get_morse_bump(self) -> int:
        return self.morse_bump

    def set_tx_selector(self, val: str) -> None:
        self.tx_selector = val
        print("TX Selector", val)

    def get_tx_selector(self) -> str:
        return self.tx_selector

    def set_tx_gain(self, val: int) -> None:
        print("TX Gain", val)


if __name__ == '__main__':
    parser = ArgumentParser("Stubbed flowgraph, for simulation purposes")
    parser.add_argument(
        "-o", "--host", default="127.0.0.2", help="address to use, default is %(default)s"
    )
    parser.add_argument(
        "-u",
        "--uplink-edl-port",
        default=10025,
        type=int,
        help="port to send edl packets, default is %(default)s",
    )
    parser.add_argument(
        "-d",
        "--doppler-xmlrpc-port",
        default=10080,
        type=int,
        help="port to connect xmlrpc to, default is %(default)s",
    )
    args = parser.parse_args()

    Edl(args.host, args.uplink_edl_port).start()
    Flowgraph(args.host, args.doppler_xmlrpc_port).start()
