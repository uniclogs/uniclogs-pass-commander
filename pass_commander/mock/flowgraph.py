#!/usr/bin/env python3

import logging
import socket
from argparse import ArgumentParser
from threading import Thread
from xmlrpc.server import SimpleXMLRPCServer

logger = logging.getLogger(__name__)


class Edl(Thread):
    def __init__(self, host: str, port: int) -> None:
        '''Thread that simulates an EDL listening connection.

        Parameters
        ----------
        host
            IP address to listen on. Recommend a non-localhost loopback (like
            127.0.0.2) because pass-commander listens on 127.0.0.1.
        port
            Port to listen on.
        '''
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.addr = (host, port)

    def run(self) -> None:
        edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        edl.bind(self.addr)
        while True:
            logger.info("EDL %s", edl.recv(4096))


class Flowgraph:
    def __init__(self, host: str, port: int) -> None:
        '''Simulate xmlrpc flowgraph interface for testing.

        Parameters
        ----------
        host
            IP address to listen on, usually localhost or some loopback.
        port
            port to listen on.
        '''
        self.morse_ident = ''
        self.tx_selector = "edl"

        self.server = SimpleXMLRPCServer((host, port), allow_none=True, logRequests=False)
        self.server.register_instance(self)

    def start(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        self.server.shutdown()

    def get_tx_center_frequency(self) -> float:
        return 1_265_000_000.0

    def get_rx_target_frequency(self) -> float:
        return 436_500_000.0

    def set_gpredict_tx_frequency(self, value: float) -> None:
        logger.info("TX Freq %f", value)

    def set_gpredict_rx_frequency(self, value: float) -> None:
        logger.info("RX Freq %f", value)

    def set_morse_ident(self, val: str) -> None:
        self.morse_ident = val
        logger.info("Morse bump %d", val)

    def get_morse_ident(self) -> int:
        return self.morse_ident

    def set_tx_selector(self, val: str) -> None:
        self.tx_selector = val
        logger.info("TX Selector %s", val)

    def get_tx_selector(self) -> str:
        return self.tx_selector

    def set_tx_gain(self, val: int) -> None:
        logger.info("TX Gain %d", val)


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
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    Edl(args.host, args.uplink_edl_port).start()
    Flowgraph(args.host, args.doppler_xmlrpc_port).start()
