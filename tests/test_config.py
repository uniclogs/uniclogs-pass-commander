import unittest
from ipaddress import IPv4Address
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir

import tomlkit

from pass_commander import config
from pass_commander.config import Config


class TestConfig(unittest.TestCase):
    @staticmethod
    def good_config() -> tomlkit.TOMLDocument:
        cfg = tomlkit.document()

        main = tomlkit.table()
        main['owmid'] = "fake-id"
        main['edl'] = ""
        main['txgain'] = 47

        hosts = tomlkit.table()
        hosts['radio'] = "127.0.0.2"
        hosts['station'] = "127.0.0.1"
        hosts['rotator'] = "127.0.0.1"

        observer = tomlkit.table()
        observer['lat'] = 45.0
        observer['lon'] = -122.0
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

    def test_valid(self):
        with NamedTemporaryFile(mode='w+') as f:
            tomlkit.dump(self.good_config(), f)
            f.flush()
            conf = Config(Path(f.name))
        self.assertEqual(conf.owmid, 'fake-id')
        self.assertEqual(conf.edl, b'')
        self.assertEqual(conf.txgain, 47)
        self.assertEqual(conf.radio, IPv4Address("127.0.0.2"))
        self.assertEqual(conf.station, IPv4Address("127.0.0.1"))
        self.assertEqual(conf.rotator, IPv4Address("127.0.0.1"))
        self.assertEqual(conf.lat, 45.0)
        self.assertEqual(conf.lon, -122.0)
        self.assertEqual(conf.alt, 500)
        self.assertEqual(conf.name, 'not-real')
        self.assertEqual(list(conf.tle_cache), ['OreSat0', '2022-026K'])

        # TleCache is optional
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            del conf['TleCache']
            tomlkit.dump(conf, f)
            f.flush()
            Config(Path(f.name))

    def test_missing(self):
        with self.assertRaises(config.ConfigNotFoundError):
            Config(Path('missing'))

    def test_invalid(self):
        with NamedTemporaryFile(mode='w+') as f:
            f.write('this is not the file you are looking for')
            f.flush()
            with self.assertRaises(config.InvalidTomlError):
                Config(Path(f.name))

    def test_extra_fields(self):
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Main']['fake'] = "foo"
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.UnknownKeyError):
                Config(Path(f.name))

        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Hosts']['fake'] = "foo"
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.UnknownKeyError):
                Config(Path(f.name))

        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Observer']['fake'] = "foo"
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.UnknownKeyError):
                Config(Path(f.name))

        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Fake'] = tomlkit.table()
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.UnknownKeyError):
                Config(Path(f.name))

        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Fake'] = 3
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.UnknownKeyError):
                Config(Path(f.name))

    def test_invalid_ip(self):
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Hosts']['radio'] = 'not an ip'
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.IpValidationError):
                Config(Path(f.name))

    def test_invalid_tle(self):
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

    def test_edl(self):
        # Valid full edl command
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Main']['edl'] = (
                'c4f53800002f0001000000e50001472ddbcc91f2fc21be1d'
                '55c941c99e2468ffdb583d0b44eb5cdb4be46dc33c18e233'
            )
            tomlkit.dump(conf, f)
            f.flush()
            Config(Path(f.name))

        # Non-hex string
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Main']['edl'] = 'not an edl command'
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.EdlValidationError):
                Config(Path(f.name))

        # Non-string
        with NamedTemporaryFile(mode='w+') as f:
            conf = self.good_config()
            conf['Main']['edl'] = 123456789
            tomlkit.dump(conf, f)
            f.flush()
            with self.assertRaises(config.KeyValidationError):
                Config(Path(f.name))

    def test_template(self):
        temp = Path(gettempdir()) / "faketemplate.toml"
        try:
            Config.template(temp)
            with self.assertRaises(config.TemplateTextError):
                Config(temp)
        finally:
            temp.unlink(missing_ok=True)

    def test_template_exists(self):
        with NamedTemporaryFile(mode='w+') as f:
            with self.assertRaises(FileExistsError):
                Config.template(Path(f.name))
