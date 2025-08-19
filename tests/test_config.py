import dataclasses
import typing
from pathlib import Path
from socket import gethostbyname

import pytest
import tomlkit
from tomlkit.toml_document import TOMLDocument

from pass_commander import config
from pass_commander.config import Config


class TestConfig:
    def test_valid(self, tmp_path: Path, good_toml: TOMLDocument) -> None:
        path = tmp_path / 'valid.toml'
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        conf = Config(path)
        assert conf.sat_id == good_toml['Main']['satellite']
        assert conf.owmid == good_toml['Main']['owmid']
        assert conf.edl == ("", good_toml['Main']['edl_port'])
        assert conf.txgain == good_toml['Main']['txgain']
        assert conf.edl_dest == (gethostbyname(good_toml['Hosts']["radio"]), Config.edl_dest[1])
        assert conf.flowgraph == (gethostbyname(good_toml['Hosts']["radio"]), Config.flowgraph[1])
        assert conf.station == (gethostbyname(good_toml['Hosts']['station']), Config.station[1])
        assert conf.rotator == Path(good_toml['Hosts']['rotator'])
        assert conf.observer.latitude.degrees == good_toml['Observer']['lat']
        assert conf.observer.longitude.degrees == good_toml['Observer']['lon']
        assert conf.observer.elevation.m == good_toml['Observer']['alt']
        assert conf.name == good_toml['Observer']['name']
        for field in dataclasses.fields(conf):
            # The toml string class, a subclass of str, was leaking through conf
            # but xmlrpc can only handle actual str. We might as well sanitize all
            # the other fields too.
            assert type(getattr(conf, field.name)) in (
                # run time type checking is kinda hard, it's gotta be one of these right?
                field.type,
                typing.get_origin(field.type),
                *typing.get_args(field.type),
            )
        assert set(conf.tle_cache) == set(good_toml['TleCache'])

        # satellite, owmid, edl_port, TleCache is optional
        del good_toml['Main']['satellite']
        del good_toml['Main']['owmid']
        del good_toml['Main']['edl_port']
        del good_toml['TleCache']
        path = tmp_path / 'optional.toml'
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
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

    @pytest.mark.parametrize(
        'entry',
        [
            ('Main', 'fake', 'foo'),
            ('Hosts', 'fake', 'foo'),
            ('Observer', 'fake', 'foo'),
            ('Fake', tomlkit.table()),
            ('Fake', 3),
        ],
    )
    def test_extra_fields(self, tmp_path: Path, good_toml: TOMLDocument, entry: tuple) -> None:
        if len(entry) == 2:
            good_toml[entry[0]] = entry[1]
        elif len(entry) == 3:
            good_toml[entry[0]][entry[1]] = entry[2]
        else:
            raise TypeError

        path = tmp_path / 'extra_field.toml'
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        with pytest.raises(config.UnknownKeyError):
            Config(path)

    def test_invalid_ip(self, tmp_path: Path, good_toml: TOMLDocument) -> None:
        good_toml['Hosts']['radio'] = 'not an ip'
        path = tmp_path / 'ip.toml'
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        with pytest.raises(config.IpValidationError):
            Config(path)

    def test_integer_lat_lon(self, tmp_path: Path, good_toml: TOMLDocument) -> None:
        good_toml['Observer']['lat'] = 45
        good_toml['Observer']['lon'] = -122
        path = tmp_path / "intlatlon.toml"
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        out = Config(path)
        assert out.observer.latitude.degrees == good_toml['Observer']['lat']
        assert out.observer.longitude.degrees == good_toml['Observer']['lon']

    @pytest.mark.parametrize(
        'latlon',
        [
            ('lat', 91.4),
            ('lat', -91.9),
            ('lon', 181.7),
            ('lon', -181.2),
        ],
    )
    def test_invalid_lat_lon(self, tmp_path: Path, good_toml: TOMLDocument, latlon: tuple) -> None:
        good_toml['Observer'][latlon[0]] = latlon[1]

        path = tmp_path / "latlon.toml"
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        with pytest.raises(config.AngleValidationError):
            Config(path)

    def test_invalid_tle_missing(self, tmp_path: Path, good_toml: TOMLDocument) -> None:
        del good_toml['TleCache']['OreSat0'][2]
        path = tmp_path / "missing.toml"
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        with pytest.raises(config.TleValidationError) as e:
            Config(path)
        assert isinstance(e.value.__cause__, IndexError)

    def test_invalid_tle_value(self, tmp_path: Path, good_toml: TOMLDocument) -> None:
        good_toml['TleCache']['OreSat0'][1] = "1 52017U 22026K   23092.5791975"
        path = tmp_path / "invalid.toml"
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
            f.flush()
        with pytest.raises(config.TleValidationError) as e:
            Config(path)
        assert isinstance(e.value.__cause__, ValueError)

    @pytest.mark.parametrize('edlport', ["12345", 1.2345])
    def test_edl(self, tmp_path: Path, good_toml: TOMLDocument, edlport: str | float) -> None:
        good_toml['Main']['edl_port'] = edlport
        path = tmp_path / "edlport.toml"
        with path.open('w+') as f:
            tomlkit.dump(good_toml, f)
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
