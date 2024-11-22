import unittest
from itertools import pairwise
from threading import Thread

import ephem

from pass_commander.Radio import Radio
from pass_commander.Tracker import Tracker
from .mock_flowgraph import Flowgraph


class test_radio(unittest.TestCase):
    def test_doppler(self):
        flowgraph = Flowgraph("127.0.0.2", 10080)
        rx = []
        tx = []
        flowgraph.server.register_function(lambda x: rx.append(x), "set_gpredict_rx_frequency")
        flowgraph.server.register_function(lambda x: tx.append(x), "set_gpredict_tx_frequency")
        fgthread = Thread(target=flowgraph.start)
        fgthread.start()

        track = Tracker(("45", "-122", 50), local_only=True, tle_cache = {
            "OreSat0": [
                "ORESAT0",
                "1 52017U 22026K   24237.61773939  .00250196  00000+0  18531-2 0  9992",
                "2 52017  97.4861 255.7395 0002474 307.8296  52.2743 15.72168729136382",
            ]
        })
        date = ephem.Date(45541.170401489704)  # start of a pass, determined through divination
        track.freshen(date)
        radio = Radio("127.0.0.2")

        for t in range(10 * 60):  # passes are about 10 minutes
            track.freshen(ephem.Date(date + t * ephem.second))
            radio.set_rx_frequency(track)
            radio.set_tx_frequency(track)

        flowgraph.stop()
        fgthread.join()
        radio.close()

        # RX doppler moves from high frequency to low frequency, passing over the center frequency
        self.assertTrue(rx[0] > radio.rxfreq > rx[-1])
        # monotonically decreasing
        self.assertTrue(all(x > y for x, y in pairwise(rx)))

        # TX does the opposite, monotonically low -> high, again passing the center frequency
        self.assertTrue(tx[0] < radio.txfreq < tx[-1])
        self.assertTrue(all(x < y for x, y in pairwise(tx)))
