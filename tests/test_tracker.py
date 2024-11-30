import unittest

import ephem

from pass_commander.Tracker import Tracker


class TestTracker(unittest.TestCase):
    def test_next_pass(self) -> None:
        track = Tracker(
            ("45", "-122", 50),
            "OreSat0",
            local_only=True,
            tle_cache={
                "OreSat0": [
                    "ORESAT0",
                    "1 52017U 22026K   24237.61773939  .00250196  00000+0  18531-2 0  9992",
                    "2 52017  97.4861 255.7395 0002474 307.8296  52.2743 15.72168729136382",
                ]
            },
        )
        date = ephem.Date(45541.170401489704)  # start of a pass, determined through divination
        np = track._next_pass_after(date)
