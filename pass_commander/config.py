from dataclasses import InitVar, dataclass, field
from ipaddress import AddressValueError, IPv4Address
from math import degrees, radians
from numbers import Real
from pathlib import Path
from socket import gaierror, gethostbyname
from typing import Any, NamedTuple, TypeAlias

import ephem
import tomlkit
from tomlkit.items import Table
from tomlkit.toml_document import TOMLDocument


class ConfigError(Exception):
    pass


class TleValidationError(ConfigError):
    def __init__(self, name: str, tle: list[str]) -> None:  # noqa: D107
        super().__init__(f'TLE for {name}')
        self.name = name
        self.tle = tle


class IpValidationError(ConfigError):
    def __init__(self, table: str | None, key: str, value: Any) -> None:  # noqa: D107 ANN401
        super().__init__(f"'{table}.{key}'")
        self.table = table
        self.key = key
        self.value = value


class KeyValidationError(ConfigError):
    def __init__(self, table: str | None, key: str, expect: str, actual: str) -> None:  # noqa: D107
        super().__init__(f"'{key}' invalid type {actual}")
        self.table = table
        self.key = key
        self.expect = expect
        self.actual = actual


class AngleValidationError(ConfigError):
    def __init__(self, table: str | None, key: str, value: Any) -> None:  # noqa: D107 ANN401
        super().__init__(f"'{table}.{key}'")
        self.table = table
        self.key = key
        self.value = value


class TemplateTextError(ConfigError):
    def __init__(self, table: str | None, key: str) -> None:  # noqa: D107
        super().__init__(f'{table}.{key}')
        self.table = table
        self.key = key


class UnknownKeyError(ConfigError):
    def __init__(self, keys: list[str]) -> None:  # noqa: D107
        super().__init__(' '.join(keys))
        self.keys = keys


class MissingKeyError(ConfigError):
    def __init__(self, table: str | None, key: str) -> None:  # noqa: D107
        super().__init__(f'{table}.{key}')
        self.table = table
        self.key = key


class MissingTableError(ConfigError):
    def __init__(self, table: str) -> None:  # noqa: D107
        super().__init__(table)
        self.table = table


class InvalidTomlError(ConfigError):
    pass


class ConfigNotFoundError(ConfigError):
    pass


class AzEl(NamedTuple):
    az: Any
    el: Any


TleCache: TypeAlias = dict[str, list[str]]
_marker = object()  # marks no default value, in case we want None as default


def _pop_table(cfg: TOMLDocument, table: str, default: Any = _marker) -> Any:  # noqa: ANN401
    try:
        entry = cfg.pop(table)
        if not isinstance(entry, Table):
            raise UnknownKeyError([table])
    except tomlkit.exceptions.NonExistentKey as e:
        if default is _marker:
            raise MissingTableError(table) from e
        entry = default
    return entry


def _pop(table: Table, key: str, valtype: type, default: Any = _marker) -> Any:  # noqa: ANN401
    try:
        val = table.pop(key)
    except tomlkit.exceptions.NonExistentKey as e:
        if default is _marker:
            raise MissingKeyError(table.display_name, key) from e
        val = default
    if not isinstance(val, valtype):
        raise KeyValidationError(table.display_name, key, valtype.__name__, type(val).__name__)
    return val


def _pop_ip(table: Table, key: str, valtype: type, default: Any = _marker) -> IPv4Address:  # noqa: ANN401
    value = _pop(table, key, valtype, default)
    try:
        return IPv4Address(gethostbyname(value))
    except (AddressValueError, gaierror) as e:
        raise IpValidationError(table.display_name, key, value) from e


def _pop_angle(table: Table, key: str, valtype: type, default: Any = _marker) -> ephem.Angle:  # noqa: ANN401
    value = _pop(table, key, valtype, default)
    try:
        value = ephem.degrees(radians(value))
    except (ValueError, TypeError) as e:
        raise AngleValidationError(table.display_name, key, value) from e
    if not radians(-180) < value < radians(180):
        raise AngleValidationError(table.display_name, key, value)
    return value


def _check_template_text(config: TOMLDocument) -> None:
    '''Ensure all template text has been removed.'''
    for name, table in config.items():
        if not isinstance(table, Table):
            continue
        for key, value in table.items():
            if isinstance(value, str) and '<' in value:
                raise TemplateTextError(name, key)


@dataclass
class Config:
    path: InitVar[Path]

    # Main
    sat_id: str = ''
    owmid: str = ''
    edl_port: int = 10025
    txgain: int = 2

    # Hosts
    radio: IPv4Address = IPv4Address('127.0.0.1')
    radio_edl: int = 10025
    radio_xmlrpc: int = 10080
    station: IPv4Address = IPv4Address('127.0.0.1')
    rotator: IPv4Address = IPv4Address('127.0.0.1')

    # Observer
    lat: ephem.Angle = ephem.degrees(radians(45.509054))
    lon: ephem.Angle = ephem.degrees(radians(-122.681394))
    alt: int = 50
    name: str = ''
    cal: AzEl = AzEl(0, 0)
    slew: AzEl | None = None
    beam_width: float | None = None

    # Satellite
    tle_cache: TleCache = field(default_factory=dict)

    # Command line only
    mock: set[str] = field(default_factory=set)
    pass_count: int = 9999

    def __post_init__(self, path: Path) -> None:
        '''Load a config from a given file.

        Checks:
        - File exists and is valid toml
        - All template text removed
        - Mandatory tables exist and are Tables
        - Optional tables, if they exist, are Tables
        - Mandatory keys exist and have values are the expected toml type
        - Optional keys, if they exist, have values that are the expected toml type
        - Values convert to the expected Config type
        - No unexpected keys/all keys consumed

        Parameters
        ----------
        path
            Path to the config file, usually pass_commander.toml
        '''
        try:
            config = tomlkit.parse(path.expanduser().read_text())
        except tomlkit.exceptions.ParseError as e:
            raise InvalidTomlError(*e.args) from e
        except FileNotFoundError as e:
            raise ConfigNotFoundError from e
        except IsADirectoryError as e:
            raise ConfigNotFoundError from e

        _check_template_text(config)

        main = _pop_table(config, 'Main')
        self.sat_id = _pop(main, 'satellite', str, self.sat_id)
        self.owmid = _pop(main, 'owmid', str, self.owmid)
        self.edl_port = _pop(main, 'edl_port', int, self.edl_port)
        self.txgain = _pop(main, 'txgain', int)

        hosts = _pop_table(config, 'Hosts')
        self.radio = _pop_ip(hosts, 'radio', str)
        self.station = _pop_ip(hosts, 'station', str)
        self.rotator = _pop_ip(hosts, 'rotator', str)

        observer = _pop_table(config, 'Observer')
        self.lat = _pop_angle(observer, 'lat', Real)
        self.lon = _pop_angle(observer, 'lon', Real)
        self.alt = _pop(observer, 'alt', int)
        self.name = str(_pop(observer, 'name', str)) # XMLRPC can't handle toml subclass

        self.tle_cache = _pop_table(config, 'TleCache', {})
        # validate TLEs
        for key, tle in self.tle_cache.items():
            try:
                ephem.readtle(*tle)
            except (TypeError, ValueError) as e:  # noqa: PERF203
                raise TleValidationError(key, tle) from e

        # Ensure there's no extra keys
        extra = ['Main.' + k for k in main]
        extra.extend('Hosts.' + k for k in hosts)
        extra.extend('Observer.' + k for k in observer)
        extra.extend(k for k in config)
        if extra:
            raise UnknownKeyError(extra)

    @classmethod
    def template(cls, path: Path) -> None:
        config = tomlkit.document()
        config.add(tomlkit.comment("Be sure to replace all <hint text> including angle brackets"))
        config.add(tomlkit.comment("Optional fields are commented out, uncomment to set"))

        main = tomlkit.table()
        main.add(tomlkit.comment('satellite = "<Index to TleCache, Gpredict, or NORAD ID>"'))
        main.add(tomlkit.comment('owmid = "<OpenWeatherMap API key>"'))
        main['edl_port'] = cls.edl_port
        main['txgain'] = cls.txgain

        hosts = tomlkit.table()
        hosts['radio'] = str(cls.radio)
        hosts['station'] = str(cls.station)
        hosts['rotator'] = str(cls.rotator)

        observer = tomlkit.table()
        observer.add(tomlkit.comment("Change lat, lon, and alt to your specific station."))
        observer.add(tomlkit.comment("These values are for the Portland evb1 station"))
        observer['lat'] = degrees(cls.lat)
        observer['lon'] = degrees(cls.lon)
        observer['alt'] = cls.alt
        observer['name'] = '<station name or callsign>'

        config['Main'] = main
        config['Hosts'] = hosts
        config['Observer'] = observer

        config.add(tomlkit.nl())
        config.add(tomlkit.comment("[TleCache]"))
        config.add(tomlkit.comment("<name> = ["))
        config.add(tomlkit.comment('    "<TLE Title>",'))
        config.add(tomlkit.comment('    "<TLE line 1>",'))
        config.add(tomlkit.comment('    "<TLE line 2>",'))
        config.add(tomlkit.comment("]"))

        path = path.expanduser()
        if path.exists():
            raise FileExistsError

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(config))
