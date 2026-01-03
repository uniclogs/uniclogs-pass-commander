# ruff: noqa: ERA001, D103
from contextlib import closing
from pathlib import Path

import pytest
import tomlkit
from tomlkit.toml_document import TOMLDocument

from pass_commander import mock
from pass_commander.config import Config
from pass_commander.satellite import Satellite


@pytest.fixture
def good_toml() -> TOMLDocument:
    cfg = tomlkit.document()

    main = tomlkit.table()
    main['satellite'] = "fake-sat"
    main['minimum-pass-elevation'] = 16
    main['owmid'] = "fake-id"
    main['edl_port'] = 12345
    main['txgain'] = 47

    hosts = tomlkit.table()
    hosts['radio'] = "localhost"
    hosts['station'] = "127.0.0.1"
    hosts['rotator'] = "/dev/null"

    observer = tomlkit.table()
    observer['lat'] = 45.509054
    observer['lon'] = -122.681394
    observer['alt'] = 500
    observer['name'] = 'not-real'
    observer['temperature-limit'] = 33.0

    cfg['Main'] = main
    cfg['Hosts'] = hosts
    cfg['Observer'] = observer

    cfg['TleCache'] = {
        'OreSat0': [
            "ORESAT0",
            "1 52017U 22026K   23092.57919752  .00024279  00000+0  10547-2 0  9990",
            "2 52017  97.5109  94.8899 0023022 355.7525   4.3512 15.22051679 58035",
        ],
        '2022-026K': [
            "ORESAT0",
            "1 52017U 22026K   23092.57919752  .00024279  00000+0  10547-2 0  9990",
            "2 52017  97.5109  94.8899 0023022 355.7525   4.3512 15.22051679 58035",
        ],
    }

    return cfg


@pytest.fixture
def good_config(tmp_path: Path, good_toml: TOMLDocument) -> Config:
    path = tmp_path / 'config.toml'
    with path.open('w+') as f:
        tomlkit.dump(good_toml, f)
        f.flush()
    return Config(path)


@pytest.fixture
def stationd() -> tuple[str, int]:
    s = mock.Stationd()
    s.start()
    try:
        yield s.addr
    finally:
        s.close()
        s.join()


@pytest.fixture(params=(1, 2, 4))
def rotator(request) -> str:  # noqa: ANN001
    with closing(mock.PtyRotator(pulses_per_degree=request.param)) as r:
        yield r.client_path


@pytest.fixture
def flowgraph() -> tuple[str, int]:
    f = mock.Flowgraph()
    f.start()
    try:
        yield f
    finally:
        f.close()
        f._thread.join()  # noqa: SLF001


@pytest.fixture
def edl() -> tuple[str, int]:
    e = mock.Edl()
    e.start()
    try:
        yield e
    finally:
        e.close()
        e.join()


tles = [
    # Geostationary
    # [
    #     "GOES 18",
    #     "1 51850U 22021A   25073.61632166  .00000091  00000+0  00000+0 0  9992",
    #     "2 51850   0.0458 328.8804 0000426 100.9638 187.4828  1.00272874 11191",
    # ],
    # Sun synchronous
    [
        "ORESAT0",
        "1 52017U 22026K   24237.61773939  .00250196  00000+0  18531-2 0  9992",
        "2 52017  97.4861 255.7395 0002474 307.8296  52.2743 15.72168729136382",
    ],
]


@pytest.fixture(params=tles)
def sat(request, tmp_path: Path) -> Satellite:  # noqa: ANN001
    name = request.param[0]
    return Satellite(name, tmp_path, tle_cache={name: request.param}, local_only=True)
