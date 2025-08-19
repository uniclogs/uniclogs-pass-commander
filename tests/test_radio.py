from contextlib import closing
from itertools import pairwise

import pytest
from skyfield.api import E, N, wgs84

from pass_commander.mock import Edl, Flowgraph
from pass_commander.radio import Radio
from pass_commander.satellite import Satellite
from pass_commander.tracker import Tracker


class TestRadio:
    @pytest.fixture
    def radio(self, flowgraph: Flowgraph, edl: Edl) -> Radio:
        with closing(Radio(flowgraph.addr, edl.addr, "TEST")) as r:
            yield r

    def test_doppler(self, sat: Satellite, flowgraph: Flowgraph, edl: Edl) -> None:
        rx = []
        tx = []
        flowgraph._server.register_function(lambda x: rx.append(x), "set_gpredict_rx_frequency")  # noqa: SLF001
        flowgraph._server.register_function(lambda x: tx.append(x), "set_gpredict_tx_frequency")  # noqa: SLF001

        with closing(Radio(flowgraph.addr, edl.addr, "TEST")) as radio:
            tracker = Tracker(wgs84.latlon(45.509054 * N, -122.681394 * E, 50))
            nextpass = tracker.next_pass(sat, after=sat.epoch)
            _, (_, rangevel) = tracker.track(sat, nextpass)

            for v in rangevel.m_per_s:
                radio.set_rx_frequency(v)
                radio.set_tx_frequency(v)

        # RX doppler moves from high frequency to low frequency, passing over the center frequency
        assert rx[0] > radio.rxfreq > rx[-1]
        # monotonically decreasing
        assert all(x > y for x, y in pairwise(rx))

        # TX does the opposite, monotonically low -> high, again passing the center frequency
        assert tx[0] < radio.txfreq < tx[-1]
        assert all(x < y for x, y in pairwise(tx))

    def test_ident(self, radio: Radio) -> None:
        radio.morse_delay = 0
        radio.ident()

    def test_selector(self, radio: Radio) -> None:
        mode = 'cw'
        radio.set_tx_selector(mode)
        assert radio.get_tx_selector() == mode

    def test_tx_gain(self, radio: Radio) -> None:
        gain = 55
        radio.set_tx_gain(gain)

    def test_morse_ident(self, radio: Radio) -> None:
        ident = "OTHER"
        radio.set_morse_ident(ident)

        # FIXME: check flowgraph value

    def test_edl(self, radio: Radio) -> None:
        packet = "test string".encode('ascii')
        radio.edl(packet, 0)
