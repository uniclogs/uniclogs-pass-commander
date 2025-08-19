import logging
import socket
from threading import Lock
from time import sleep
from xmlrpc.client import ServerProxy

from skyfield import constants

logger = logging.getLogger(__name__)


class Radio:
    def __init__(
        self, flowgraph: tuple[str, int], edl: tuple[str, int], name: str, morse_delay: float = 4.0
    ) -> None:
        '''Binding to the uniclogs-sdr GNURadio flowgraph.

        The flowgraph exposes an xmlrpc interface for configuration and setting doppler offsets.
        It additionally has a UDP port for EDL communication.

        Parameters
        ----------
        flowgraph
            IP and port of the flowgraph xmlrpc server
        edl
            IP and port of the EDL UDP socket
        name
            station identifier to be sent out over morse
        morse_delay
            duration in seconds to wait for the morse identifier broadcast to complete
        '''
        self._edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._edl.connect(edl)
        self._lock = Lock()
        self._flowgraph = ServerProxy(f"http://{flowgraph[0]}:{flowgraph[1]}")
        tx = self._flowgraph.get_tx_center_frequency()
        rx = self._flowgraph.get_rx_target_frequency()
        if not isinstance(tx, float):
            raise TypeError("Flowgraph returned invalid tx type")
        if not isinstance(rx, float):
            raise TypeError("Flowgraph returned invalid rx type")
        self.txfreq = tx
        self.rxfreq = rx
        self.name = name
        # FIXME: infer default delay from name
        self.morse_delay = morse_delay

    def ident(self) -> None:
        old_selector = self.get_tx_selector()
        self.set_tx_selector("morse")
        self.set_morse_ident(self.name)
        sleep(self.morse_delay)
        self.set_tx_selector(old_selector)

    def rx_frequency(self, range_velocity: float) -> float:
        # RX on the ground frequency. range_velocity is the satellite relative velocity, it
        # starts negative and goes positive so the frequency starts high and goes low
        return float(1 - range_velocity / constants.C) * self.rxfreq

    def set_rx_frequency(self, range_velocity: float) -> None:
        freq = self.rx_frequency(range_velocity)
        logger.info("Set RX frequency %.1f", freq)
        with self._lock:
            self._flowgraph.set_gpredict_rx_frequency(freq)

    def tx_frequency(self, range_velocity: float) -> float:
        # TX is the opposite of RX, starts low, goes high
        return float(1 + range_velocity / constants.C) * self.txfreq

    def set_tx_frequency(self, range_velocity: float) -> None:
        freq = self.tx_frequency(range_velocity)
        logger.info("Set TX frequency %.1f", freq)
        with self._lock:
            self._flowgraph.set_gpredict_tx_frequency(freq)

    def set_tx_selector(self, mode: str) -> None:
        logger.info("Selecting mode %s", mode)
        with self._lock:
            self._flowgraph.set_tx_selector(mode)

    def get_tx_selector(self) -> str:
        with self._lock:
            val = self._flowgraph.get_tx_selector()
            if not isinstance(val, str):
                raise TypeError("Flowgraph returned invalid tx_selector type")
            return val

    def set_tx_gain(self, gain: int) -> None:
        logger.info("Setting gain %s", gain)
        with self._lock:
            self._flowgraph.set_tx_gain(gain)

    def set_morse_ident(self, ident: str) -> None:
        logger.info("Sending morse ident %s", ident)
        with self._lock:
            self._flowgraph.set_morse_ident(ident)

    def edl(self, packet: bytes, range_velocity: float) -> None:
        self.set_tx_frequency(range_velocity)
        self._edl.send(packet)

    def close(self) -> None:
        # FIXME: close _flowgraph?
        self._edl.close()
