import unittest
from ipaddress import IPv4Address
from math import radians
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir

import tomlkit
from tomlkit.toml_document import TOMLDocument

from pass_commander import config
from pass_commander.config import Config


class TestConfig(unittest.TestCase):
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

    def test_valid(self) -> None:
        with NamedTemporaryFile(mode='w+') as f:
            tomlkit.dump(self.good_config(), f)
            f.flush()
            conf = Config(Path(f.name))
        self.assertEqual(conf.owmid, 'fake-id')
        self.assertEqual(conf.edl_port, 12345)
        self.assertEqual(conf.txgain, 47)
        self.assertEqual(conf.radio, IPv4Address("127.0.0.1"))
        self.assertEqual(conf.station, IPv4Address("127.0.0.1"))
        self.assertEqual(conf.rotator, IPv4Address("127.0.0.2"))
        self.assertEqual(conf.lat, radians(45.509054))
        self.assertEqual(conf.lon, radians(-122.681394))
        self.assertEqual(conf.alt, 500)
        self.assertEqual(conf.name, 'not-real')
        self.assertEqual(list(conf.tle_cache), ['OreSat0', '2022-026K'])

        # satellite, owmid, edl_port, TleCache is optional
        with NamedTemporaryFile(mode='w+') as f:
            cfg = self.good_config()
            del cfg['Main']['satellite']
            del cfg['Main']['owmid']
            del cfg['Main']['edl_port']
            del cfg['TleCache']
            tomlkit.dump(cfg, f)
            f.flush()
            Config(Path(f.name))

    def test_missing(self) -> None:
        with self.assertRaises(config.ConfigNotFoundError):
            Config(Path('missing'))

    def test_invalid(self) -> None:
        with NamedTemporaryFile(mode='w+') as f:
            f.write('this is not the file you are looking for')
            f.flush()
            with self.assertRaises(config.InvalidTomlError):
                Config(Path(f.name))

    def test_extra_fields(self) -> None:
        cases = [self.good_config() for _ in range(5)]
        cases[0]['Main']['fake'] = "foo"
        cases[1]['Hosts']['fake'] = "foo"
        cases[2]['Observer']['fake'] = "foo"
        cases[3]['Fake'] = tomlkit.table()
        cases[4]['Fake'] = 3

        for conf in cases:
            with NamedTemporaryFile(mode='w+') as f:
                tomlkit.dump(conf, f)
                f.flush()
                with self.assertRaises(config.UnknownKeyError):
                    Config(Path(f.name))

    def test_invalid_ip(self) -> None:
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Hosts']['radio'] = 'not an ip'
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.IpValidationError):
                Config(Path(f.name))

    def test_integer_lat_lon(self) -> None:
        conf = self.good_config()
        conf['Observer']['lat'] = 45
        conf['Observer']['lat'] = -122
        with NamedTemporaryFile(mode='w+') as f:
            tomlkit.dump(conf, f)
            f.flush()
            out = Config(Path(f.name))
            self.assertEqual(out.lat, radians(conf['Observer']['lat']))
            self.assertEqual(out.lon, radians(conf['Observer']['lon']))

    def test_invalid_lat_lon(self) -> None:
        cases = [self.good_config() for _ in range(4)]
        cases[0]['Observer']['lat'] = 270.4
        cases[1]['Observer']['lat'] = -270.9
        cases[2]['Observer']['lon'] = 270.7
        cases[3]['Observer']['lon'] = -270.2
        for conf in cases:
            with NamedTemporaryFile(mode='w+') as f:
                tomlkit.dump(conf, f)
                f.flush()
                with self.assertRaises(config.AngleValidationError):
                    Config(Path(f.name))

    def test_invalid_tle(self) -> None:
        # Missing lines TypeError
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            del conf['TleCache']['OreSat0'][2]
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.TleValidationError) as e:
                Config(Path(f.name))
            self.assertIsInstance(e.exception.__cause__, TypeError)

        # Invalid lines ValueError
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['TleCache']['OreSat0'][1] = "1 52017U 22026K   23092.5791975"
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.TleValidationError) as e:
                Config(Path(f.name))
            self.assertIsInstance(e.exception.__cause__, ValueError)

    def test_edl(self) -> None:
        # String
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Main']['edl_port'] = "12345"
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.KeyValidationError):
                Config(Path(f.name))

        # Float
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Main']['edl_port'] = 1.2345
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.KeyValidationError):
                Config(Path(f.name))

    def test_template(self) -> None:
        temp = Path(gettempdir()) / "faketemplate.toml"
        try:
            Config.template(temp)
            with self.assertRaises(config.TemplateTextError):
                Config(temp)
        finally:
            temp.unlink(missing_ok=True)

    def test_template_exists(self) -> None:
        with NamedTemporaryFile(mode='w+') as f:
            with self.assertRaises(FileExistsError):
                Config.template(Path(f.name))
