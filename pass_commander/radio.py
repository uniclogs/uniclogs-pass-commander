import socket
from threading import Lock
from time import sleep
from xmlrpc.client import ServerProxy

from .tracker import Tracker


class Radio:
    def __init__(self, host: str, xml_port: int, edl_port: int):
        self._edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._edl.connect((host, edl_port))
        self._lock = Lock()
        self._flowgraph = ServerProxy(f"http://{host}:{xml_port}")
        tx = self._flowgraph.get_tx_center_frequency()
        rx = self._flowgraph.get_rx_target_frequency()
        assert isinstance(tx, float)
        assert isinstance(rx, float)
        self.txfreq = tx
        self.rxfreq = rx

    def ident(self, delay: int = 4) -> None:
        old_selector = self.get_tx_selector()
        self.set_tx_selector("morse")
        self.set_morse_bump(self.get_morse_bump() ^ 1)
        sleep(delay)
        self.set_tx_selector(old_selector)

    def rx_frequency(self, track: Tracker) -> float:
        # RX on the ground frequeny. track.doppler is the satellite relative velocity scaled, so it
        # starts negative and goes positive, so the frequency starts high and goes low
        return (1 - track.doppler) * self.rxfreq

    def set_rx_frequency(self, track: Tracker) -> None:
        with self._lock:
            self._flowgraph.set_gpredict_rx_frequency(self.rx_frequency(track))

    def tx_frequency(self, track: Tracker) -> float:
        # TX is the opposite of RX, starts low, goes high
        return (1 + track.doppler) * self.txfreq

    def set_tx_frequency(self, track: Tracker) -> None:
        with self._lock:
            self._flowgraph.set_gpredict_tx_frequency(self.tx_frequency(track))

    def set_tx_selector(self, mode: str) -> None:
        with self._lock:
            self._flowgraph.set_tx_selector(mode)

    def get_tx_selector(self) -> str:
        with self._lock:
            val = self._flowgraph.get_tx_selector()
            assert isinstance(val, str)
            return val

    def set_tx_gain(self, gain: int) -> None:
        with self._lock:
            self._flowgraph.set_tx_gain(gain)

    def set_morse_bump(self, bump: int) -> None:
        with self._lock:
            self._flowgraph.set_morse_bump(bump)

    def get_morse_bump(self) -> int:
        with self._lock:
            val = self._flowgraph.get_morse_bump()
            assert isinstance(val, int)
            return val

    def edl(self, packet: bytes) -> None:
        self._edl.send(packet)

    def close(self) -> None:
        self._edl.close()
