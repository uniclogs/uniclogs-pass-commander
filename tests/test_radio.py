from itertools import pairwise
from threading import Thread

import ephem

from pass_commander.mock import Edl, Flowgraph
from pass_commander.radio import Radio
from pass_commander.tracker import Tracker


class TestRadio:
    def test_doppler(self) -> None:
        flowgraph = Flowgraph("127.0.0.2", 10080)
        rx = []
        tx = []
        flowgraph.server.register_function(lambda x: rx.append(x), "set_gpredict_rx_frequency")
        flowgraph.server.register_function(lambda x: tx.append(x), "set_gpredict_tx_frequency")
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()

        track = Tracker(
            (ephem.degrees(45), ephem.degrees(-122), 50),
            "OreSat0",
            local_only=True,
            tle_cache={
                "OreSat0": [
                    "ORESAT0",
                    "1 52017U 22026K   24237.61773939  .00250196  00000+0  18531-2 0  9992",
                    "2 52017  97.4861 255.7395 0002474 307.8296  52.2743 15.72168729136382",
                ],
            },
        )
        date = ephem.Date(45541.170401489704)  # start of a pass, determined through divination
        track.freshen(date)
        radio = Radio("127.0.0.2", 10080, 10025)

        for t in range(10 * 60):  # passes are about 10 minutes
            track.freshen(ephem.Date(date + t * ephem.second))
            radio.set_rx_frequency(track)
            radio.set_tx_frequency(track)

        flowgraph.stop()
        fgthread.join()
        radio.close()

        # RX doppler moves from high frequency to low frequency, passing over the center frequency
        assert rx[0] > radio.rxfreq > rx[-1]
        # monotonically decreasing
        assert all(x > y for x, y in pairwise(rx))

        # TX does the opposite, monotonically low -> high, again passing the center frequency
        assert tx[0] < radio.txfreq < tx[-1]
        assert all(x < y for x, y in pairwise(tx))

    def test_ident(self) -> None:
        addr = ("127.0.0.2", 10081)
        flowgraph = Flowgraph(*addr)
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()
        radio = Radio(*addr, 10025)

        radio.ident(delay=0)

        flowgraph.stop()
        fgthread.join()
        radio.close()

    def test_selector(self) -> None:
        addr = ("127.0.0.2", 10082)
        flowgraph = Flowgraph(*addr)
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()
        radio = Radio(*addr, 10025)

        mode = 'cw'
        radio.set_tx_selector(mode)
        assert radio.get_tx_selector() == mode

        flowgraph.stop()
        fgthread.join()
        radio.close()

    def test_tx_gain(self) -> None:
        addr = ("127.0.0.2", 10083)
        flowgraph = Flowgraph(*addr)
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()
        radio = Radio(*addr, 10025)

        gain = 55
        radio.set_tx_gain(gain)

        flowgraph.stop()
        fgthread.join()
        radio.close()

    def test_morse_bump(self) -> None:
        addr = ("127.0.0.2", 10084)
        flowgraph = Flowgraph(*addr)
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()
        radio = Radio(*addr, 10025)

        bump = 0
        radio.set_morse_bump(bump)
        assert radio.get_morse_bump() == bump

        bump = 1
        radio.set_morse_bump(bump)
        assert radio.get_morse_bump() == bump

        flowgraph.stop()
        fgthread.join()
        radio.close()

    def test_edl(self) -> None:
        addr = ("127.0.0.2", 10085)
        flowgraph = Flowgraph(*addr)
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()
        Edl("127.0.0.2", 10026).start()
        radio = Radio(*addr, 10026)

        packet = "test string".encode('ascii')
        radio.edl(packet)

        flowgraph.stop()
        fgthread.join()
        radio.close()
