from ipaddress import IPv4Address
from math import radians
from pathlib import Path
from socket import gethostbyname

import pytest
import tomlkit
from tomlkit.toml_document import TOMLDocument

from pass_commander import config
from pass_commander.config import Config


class TestConfig:
    @staticmethod
    def good_config() -> TOMLDocument:
        cfg = tomlkit.document()

        main = tomlkit.table()
        main['satellite'] = "fake-sat"
        main['owmid'] = "fake-id"
        main['edl_port'] = 12345
        main['txgain'] = 47

        hosts = tomlkit.table()
        hosts['radio'] = "localhost"
        hosts['station'] = "127.0.0.1"
        hosts['rotator'] = "127.0.0.2"

        observer = tomlkit.table()
        observer['lat'] = 45.509054
        observer['lon'] = -122.681394
        observer['alt'] = 500
        observer['name'] = 'not-real'

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

    def test_valid(self, tmp_path: Path) -> None:
        path = tmp_path / 'valid.toml'
        good = self.good_config()
        with path.open('w+') as f:
            tomlkit.dump(good, f)
            f.flush()
        conf = Config(path)
        assert conf.sat_id == good['Main']['satellite']
        assert conf.owmid == good['Main']['owmid']
        assert conf.edl_port == good['Main']['edl_port']
        assert conf.txgain == good['Main']['txgain']
        assert conf.radio == IPv4Address(gethostbyname(good['Hosts']["radio"]))
        assert conf.station == IPv4Address(gethostbyname(good['Hosts']['station']))
        assert conf.rotator == IPv4Address(gethostbyname(good['Hosts']['rotator']))
        assert conf.lat == radians(good['Observer']['lat'])
        assert conf.lon == radians(good['Observer']['lon'])
        assert conf.alt == good['Observer']['alt']
        assert conf.name == good['Observer']['name']
        assert set(conf.tle_cache) == set(good['TleCache'])

        # satellite, owmid, edl_port, TleCache is optional
        cfg = self.good_config()
        del cfg['Main']['satellite']
        del cfg['Main']['owmid']
        del cfg['Main']['edl_port']
        del cfg['TleCache']
        path = tmp_path / 'optional.toml'
        with path.open('w+') as f:
            tomlkit.dump(cfg, f)
            f.flush()
        Config(path)

    def test_missing(self, tmp_path: Path) -> None:
        with pytest.raises(config.ConfigNotFoundError):
            Config(tmp_path / 'missing')

    def test_invalid(self, tmp_path: Path) -> None:
        path = tmp_path / 'invalid.toml'
        with path.open('w+') as f:
            f.write('this is not the file you are looking for')
            f.flush()
        with pytest.raises(config.InvalidTomlError):
            Config(path)

    def test_extra_fields(self, tmp_path: Path) -> None:
        cases = [self.good_config() for _ in range(5)]
        cases[0]['Main']['fake'] = "foo"
        cases[1]['Hosts']['fake'] = "foo"
        cases[2]['Observer']['fake'] = "foo"
        cases[3]['Fake'] = tomlkit.table()
        cases[4]['Fake'] = 3

        for i, conf in enumerate(cases):
            path = tmp_path / f'case{i}.toml'
            with path.open('w+') as f:
                tomlkit.dump(conf, f)
                f.flush()
            with pytest.raises(config.UnknownKeyError):
                Config(path)

    def test_invalid_ip(self, tmp_path: Path) -> None:
        conf = self.good_config()
        conf['Hosts']['radio'] = 'not an ip'
        path = tmp_path / 'ip.toml'
        with path.open('w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
        with pytest.raises(config.IpValidationError):
            Config(path)

    def test_integer_lat_lon(self, tmp_path: Path) -> None:
        conf = self.good_config()
        conf['Observer']['lat'] = 45
        conf['Observer']['lat'] = -122
        path = tmp_path / "intlatlon.toml"
        with path.open('w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
        out = Config(path)
        assert out.lat == radians(conf['Observer']['lat'])
        assert out.lon == radians(conf['Observer']['lon'])

    def test_invalid_lat_lon(self, tmp_path: Path) -> None:
        cases = [self.good_config() for _ in range(4)]
        cases[0]['Observer']['lat'] = 270.4
        cases[1]['Observer']['lat'] = -270.9
        cases[2]['Observer']['lon'] = 270.7
        cases[3]['Observer']['lon'] = -270.2
        for i, conf in enumerate(cases):
            path = tmp_path / f"case{i}.toml"
            with path.open('w+') as f:
                tomlkit.dump(conf, f)
                f.flush()
            with pytest.raises(config.AngleValidationError):
                Config(path)

    def test_invalid_tle(self, tmp_path: Path) -> None:
        # Missing lines TypeError
        conf = self.good_config()
        del conf['TleCache']['OreSat0'][2]
        path = tmp_path / "missing.toml"
        with path.open('w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
        with pytest.raises(config.TleValidationError) as e:
            Config(path)
        assert isinstance(e.value.__cause__, TypeError)

        # Invalid lines ValueError
        conf = self.good_config()
        conf['TleCache']['OreSat0'][1] = "1 52017U 22026K   23092.5791975"
        path = tmp_path / "invalid.toml"
        with path.open('w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
        with pytest.raises(config.TleValidationError) as e:
            Config(path)
        assert isinstance(e.value.__cause__, ValueError)

    def test_edl(self, tmp_path: Path) -> None:
        # String
        conf = self.good_config()
        conf['Main']['edl_port'] = "12345"
        path = tmp_path / "string.toml"
        with path.open('w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
        with pytest.raises(config.KeyValidationError):
            Config(path)

        # Float
        conf = self.good_config()
        conf['Main']['edl_port'] = 1.2345
        path = tmp_path / "float.toml"
        with path.open('w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
        with pytest.raises(config.KeyValidationError):
            Config(path)

    def test_template(self, tmp_path: Path) -> None:
        Config.template(tmp_path / "faketemplate.toml")
        with pytest.raises(config.TemplateTextError):
            Config(tmp_path / "faketemplate.toml")

    def test_template_exists(self, tmp_path: Path) -> None:
        conf = tmp_path / "config.toml"
        conf.touch()
        with pytest.raises(FileExistsError):
            Config.template(conf)
