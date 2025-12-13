from pathlib import Path
from typing import Final

import pytest
import requests
import responses

from pass_commander.satellite import Satellite


class TestSatellite:
    # Args: sat_id, tle_cache, local_only
    # Sat ID types:
    # - 2024-149BK
    # - 60525
    # - ORESAT0.5
    # tle_cache some/none/sat not found
    # local_only t/f
    # celestrak success/fail/sat not found
    # how to test gpredict?
    # A sat not found via any method

    tle: Final[list[str]] = [
        'ORESAT0.5',
        '1 60525U 24149BK  25028.49486722  .00019661  00000+0  77233-3 0  9994',
        '2 60525  97.4192 108.1185 0006873 288.2875  71.7615 15.25712956 25052',
    ]

    names: Final[list[str]] = [
        '2024-149BK',
        '60525',
        'ORESAT0.5',
    ]

    @responses.activate
    def test_cache(self, tmp_path: Path) -> None:
        cache = dict.fromkeys(self.names, self.tle)

        for name in self.names:
            Satellite(name, tmp_path, tle_cache=cache, local_only=True)

        with pytest.raises(ValueError, match=r"^Invalid satellite identifier"):
            Satellite('invalid', tmp_path, tle_cache=cache, local_only=True)

    @responses.activate
    def test_celestrak(self, tmp_path: Path) -> None:
        # valid
        # missing
        # timeout
        # 403

        valid = responses.Response(
            method="GET",
            url=f"https://celestrak.org/NORAD/elements/gp.php?CATNR={self.names[1]}",
            body='\n'.join(self.tle),
        )
        missing = responses.Response(
            method="GET",
            url="https://celestrak.org/NORAD/elements/gp.php?NAME=missing",
            body='No GP data found',
        )
        forbidden = responses.Response(
            method="GET",
            url="https://celestrak.org/NORAD/elements/gp.php?NAME=forbidden",
            status=403,
        )
        responses.add(valid)
        responses.add(missing)
        responses.add(forbidden)

        Satellite(self.names[1], tmp_path)

        with pytest.raises(ValueError, match=r"^Invalid satellite identifier"):
            Satellite('missing', tmp_path)

        with pytest.raises(requests.exceptions.HTTPError):
            Satellite('forbidden', tmp_path)

    @responses.activate
    def test_cache_fallback(self, tmp_path: Path) -> None:
        fallback = responses.Response(
            method="GET",
            url="https://celestrak.org/NORAD/elements/gp.php?NAME=fallback",
            body='No GP data found',
        )
        responses.add(fallback)

        Satellite('fallback', tmp_path, tle_cache={'fallback': self.tle})
