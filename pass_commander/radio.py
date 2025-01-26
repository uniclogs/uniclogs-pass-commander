import socket
from threading import Lock
from time import sleep
from xmlrpc.client import ServerProxy

from .tracker import Tracker


class Radio:
    def __init__(self, host: str, xml_port: int, edl_port: int, name: str) -> None:
        '''Binding to the uniclogs-sdr GNURadio flowgraph.

        The flowgraph exposes an xmlrpc interface for configuration and setting doppler offsets.
        It additionally has a UDP port for EDL communication.

        Parameters
        ----------
        host
            IP address of the radio
        xml_port
            port of the xmlrpc server
        edl_port
            port of the EDL UDP socket
        name
            station identifier to be sent out over morse
        '''
        self._edl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._edl.connect((host, edl_port))
        self._lock = Lock()
        self._flowgraph = ServerProxy(f"http://{host}:{xml_port}")
        tx = self._flowgraph.get_tx_center_frequency()
        rx = self._flowgraph.get_rx_target_frequency()
        if not isinstance(tx, float):
            raise TypeError("Flowgraph returned invalid tx type")
        if not isinstance(rx, float):
            raise TypeError("Flowgraph returned invalid rx type")
        self.txfreq = tx
        self.rxfreq = rx
        self.name = name

    def ident(self, delay: int = 4) -> None:
        old_selector = self.get_tx_selector()
        self.set_tx_selector("morse")
        self.set_morse_ident(self.name)
        sleep(delay)
        self.set_tx_selector(old_selector)

    def rx_frequency(self, track: Tracker) -> float:
        # RX on the ground frequency. track.doppler is the satellite relative velocity scaled, so it
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
            if not isinstance(val, str):
                raise TypeError("Flowgraph returned invalid tx_selector type")
            return val

    def set_tx_gain(self, gain: int) -> None:
        with self._lock:
            self._flowgraph.set_tx_gain(gain)

    def set_morse_ident(self, ident: str) -> None:
        with self._lock:
            self._flowgraph.set_morse_ident(ident)

    def edl(self, packet: bytes) -> None:
        self._edl.send(packet)

    def close(self) -> None:
        self._edl.close()
