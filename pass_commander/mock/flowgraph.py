#!/usr/bin/env python3

import logging
import os
import selectors
import socket
from argparse import ArgumentParser
from threading import Thread
from xmlrpc.server import SimpleXMLRPCServer

logger = logging.getLogger(__name__)


class Edl(Thread):
    def __init__(self, addr: tuple[str, int] | None = None) -> None:
        '''Thread that simulates an EDL listening connection.

        Parameters
        ----------
        addr
            IP address and port to listen on. Recommend a non-localhost loopback (like
            127.0.0.2) because pass-commander listens on 127.0.0.1.
        '''
        super().__init__(name=self.__class__.__name__, daemon=True)
        if addr is None:
            addr = ('127.0.0.1', 0)
        self._edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        self._edl.bind(addr)
        self._addr: tuple[str, int] = self._edl.getsockname()
        self._r, self._w = os.pipe2(os.O_NONBLOCK)

    @property
    def addr(self) -> tuple[str, int]:
        return self._addr

    def _respond(self) -> bool:
        logger.info("EDL %s", self._edl.recv(4096))
        return False

    def run(self) -> None:
        sel = selectors.DefaultSelector()
        sel.register(self._edl, selectors.EVENT_READ, self._respond)
        sel.register(self._r, selectors.EVENT_READ, lambda: True)

        stop = False
        while not stop:
            for key, _ in sel.select():
                if stop := key.data():
                    break

        sel.close()
        self._edl.close()
        os.close(self._r)
        os.close(self._w)
        logger.info("Stopped")

    def close(self) -> None:
        os.write(self._w, b's')


class FlowgraphState:
    def __init__(self) -> None:
        '''Track the internal simulated flowgraph state.'''
        self.morse_ident = ''
        self.tx_selector = "edl"

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
        logger.info("Morse ident %s:", val)

    def get_morse_ident(self) -> str:
        return self.morse_ident

    def set_tx_selector(self, val: str) -> None:
        self.tx_selector = val
        logger.info("TX Selector %s", val)

    def get_tx_selector(self) -> str:
        return self.tx_selector

    def set_tx_gain(self, val: int) -> None:
        logger.info("TX Gain %d", val)


class Flowgraph:
    def __init__(self, addr: tuple[str, int] | None = None) -> None:
        '''Simulate xmlrpc flowgraph interface for testing.

        Parameters
        ----------
        addr
            IP address and port to listen on, usually localhost or some loopback.
        '''
        if addr is None:
            addr = ('127.0.0.1', 0)
        self._state = FlowgraphState()
        self._server = SimpleXMLRPCServer(addr, allow_none=True, logRequests=False)
        self._addr: tuple[str, int] = self._server.socket.getsockname()
        self._server.register_instance(self._state)

        self._r, self._w = os.pipe2(os.O_NONBLOCK)
        self._thread = Thread(target=self._run)

    @property
    def addr(self) -> tuple[str, int]:
        return self._addr

    def _handle(self) -> bool:
        self._server.handle_request()
        return False

    def _run(self) -> None:
        # The stock SimpleXMLRPCServer is based on socketserver that has its own serve_forever
        # but the implementation is based on a half second timeout (and there's a note in the
        # source that says pls fix) which makes unit tests slow. We already do the right thing
        # elsewhere so we can just rebuild it here.
        sel = selectors.DefaultSelector()
        sel.register(self._server, selectors.EVENT_READ, self._handle)
        sel.register(self._r, selectors.EVENT_READ, lambda: True)

        stop = False
        while not stop:
            for key, _ in sel.select():
                if stop := key.data():
                    break

        sel.close()
        self._server.server_close()
        os.close(self._r)
        os.close(self._w)
        logger.info("Stopped")

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        os.write(self._w, b's')


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

    Edl((args.host, args.uplink_edl_port)).start()
    Flowgraph((args.host, args.doppler_xmlrpc_port)).start()
