import logging
import re
from pathlib import Path
from time import time

import requests
from skyfield.api import EarthSatellite

from .config import TleCache

logger = logging.getLogger(__name__)


class Satellite(EarthSatellite):  # type: ignore[misc]
    def __init__(
        self,
        sat_id: str,
        conf_dir: Path,
        *,
        tle_cache: TleCache | None = None,
        local_only: bool = False,
    ) -> None:
        '''Fetch a TLE and build a satellite.

        Ideally fetched close to a pass for an up-to-date TLE.

        ID formats:
        - International Designator/COSPAR ID: 4 digit year, optional dash, 3
            digit launch number, up to 3 letter sequential identifier
            Example: 2024-149BK
        - NORAD Catalog Number: up to 9 digit number (typically 5)
            Example: 60525
        - Name: official name as it appears in the satellite catalog
            Example: ORESAT0.5

        Parameters
        ----------
        sat_id
            The ID of the satellite, either as an International Designator, a NORAD Satellite
            Catalog number, or Catalog satellite name.
        conf_dir
            Path to the directory to save TLEs from Celestrak in. When in doubt the same directory
            that pass_commander.toml is in is good.
        local_only
            If true, do not use the internet for TLE lookup, only tle_cache or Gpredict.
        tle_cache
            A local cache of TLEs for lookup.
        '''
        query = "NAME"
        if re.match(r"^\d{4}-?\d{3}[A-Z]{1,3}$", sat_id.upper()):
            query = "INTDES"
        elif re.match(r"^\d{1,9}$", sat_id):
            query = "CATNR"
        filename = conf_dir / f'{query}-{sat_id}.txt'

        # see https://celestrak.org/NORAD/documentation/gp-data-formats.php
        # In particular a 2 hour minimum cache time. In practice I think we get one new TLE per day
        # so here we wait 0.5 days. FIXME: Add to TLE cache/save in pass_commander.toml? Depends on
        # pydantic.
        expired = not filename.exists() or (time() - filename.stat().st_mtime > 12 * 60 * 60)
        if not local_only and expired:
            logger.info("fetching TLE from celestrak for %s", sat_id)
            r = requests.get(
                "https://celestrak.org/NORAD/elements/gp.php",
                params={query: sat_id},
                timeout=10,
            )
            r.raise_for_status()
            filename.write_text(r.text)

        tle = None
        if tle is None and filename.exists():
            logger.info("using cached TLE from %s", filename)
            lines = filename.read_text().splitlines()
            # Not documented but CelesTrak currently returns this string if the previous query
            # didn't match an object it knows about. We have to cache it anyway to respect their
            # policy.
            if lines[0] == "No GP data found":
                logger.info("No results for %s at celestrak", sat_id)
            else:
                tle = lines

        if tle is None and tle_cache and sat_id in tle_cache:
            logger.info("using cached TLE from pass_commander.toml")
            tle = tle_cache[sat_id]

        if tle is None and query == "CATNR":
            fname = Path.home() / f'.config/Gpredict/satdata{sat_id}.sat'
            if fname.is_file():
                logger.info("using Gpredict's cached TLE")
                with fname.open(encoding="ascii") as file:
                    lines = file.readlines()[3:6]
                    tle = [line.rstrip().split("=")[1] for line in lines]

        if tle is None:
            logger.info("No matching TLE for %s is available", sat_id)
            raise ValueError(f"Invalid satellite identifier: {sat_id}")

        logger.info("\n".join(tle))

        super().__init__(tle[1], tle[2], tle[0])
