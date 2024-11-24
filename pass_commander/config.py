from collections import namedtuple
from dataclasses import InitVar, dataclass, field
from ipaddress import AddressValueError, IPv4Address
from math import degrees, radians
from numbers import Number
from pathlib import Path
from socket import gaierror, gethostbyname
from typing import Any, Optional, TypeAlias

import ephem
import tomlkit
from tomlkit.items import Table
from tomlkit.toml_document import TOMLDocument


class ConfigError(Exception):
    pass


class TleValidationError(ConfigError):
    def __init__(self, name: str, tle: list[str]):
        super().__init__(f'TLE for {name}')
        self.name = name
        self.tle = tle


class IpValidationError(ConfigError):
    def __init__(self, table: Optional[str], key: str, value: Any):
        super().__init__(f"'{table}.{key}'")
        self.table = table
        self.key = key
        self.value = value


class KeyValidationError(ConfigError):
    def __init__(self, table: Optional[str], key: str, expect: str, actual: str):
        super().__init__(f"'{key}' invalid type {actual}")
        self.table = table
        self.key = key
        self.expect = expect
        self.actual = actual


class AngleValidationError(ConfigError):
    def __init__(self, table: Optional[str], key: str, value: Any):
        super().__init__(f"'{table}.{key}'")
        self.table = table
        self.key = key
        self.value = value


class TemplateTextError(ConfigError):
    def __init__(self, table: Optional[str], key: str):
        super().__init__(f'{table}.{key}')
        self.table = table
        self.key = key


class UnknownKeyError(ConfigError):
    def __init__(self, keys: list[str]):
        super().__init__(' '.join(keys))
        self.keys = keys


class MissingKeyError(ConfigError):
    def __init__(self, table: Optional[str], key: str):
        super().__init__(f'{table}.{key}')
        self.table = table
        self.key = key


class MissingTableError(ConfigError):
    def __init__(self, table: str):
        super().__init__(table)
        self.table = table


class InvalidTomlError(ConfigError):
    pass


class ConfigNotFoundError(ConfigError):
    pass


AzEl = namedtuple('AzEl', ['az', 'el'])
TleCache: TypeAlias = dict[str, list[str]]


@dataclass
class Config:
    path: InitVar[Path]

    # [Main]
    sat_id: str = ''
    owmid: str = ''
    edl_port: int = 10025
    txgain: int = 2

    # [Hosts]
    radio: IPv4Address = IPv4Address('127.0.0.1')
    station: IPv4Address = IPv4Address('127.0.0.1')
    rotator: IPv4Address = IPv4Address('127.0.0.1')

    # [Observer]
    lat: ephem.Angle = ephem.degrees(radians(45.509054))
    lon: ephem.Angle = ephem.degrees(radians(-122.681394))
    alt: int = 50
    name: str = ''
    cal: AzEl = AzEl(0, 0)
    slew: Optional[AzEl] = None
    beam_width: Optional[float] = None

    # Satellite
    tle_cache: TleCache = field(default_factory=dict)

    # Command line only
    mock: set[str] = field(default_factory=set)
    pass_count: int = 9999

    def __post_init__(self, path: Path) -> None:

        # Checks:
        # - File exists and is valid toml
        # - All template text removed
        # - Mandatory tables exist and are Tables
        # - Optional tables, if they exist, are Tables
        # - Mandatory keys exist and have values are the expected toml type
        # - Optional keys, if they exist, have values that are the expected toml type
        # - Values convert to the expected Config type
        # - No unexpected keys/all keys consumed

        try:
            config = tomlkit.parse(path.expanduser().read_text())
        except tomlkit.exceptions.ParseError as e:
            raise InvalidTomlError(*e.args) from e
        except FileNotFoundError as e:
            raise ConfigNotFoundError from e
        except IsADirectoryError as e:
            raise ConfigNotFoundError from e

        # Ensure all template text has been removed
        for name, table in config.items():
            if not isinstance(table, Table):
                continue
            for key, value in table.items():
                if isinstance(value, str) and '<' in value:
                    raise TemplateTextError(name, key)

        marker = object()  # marks no default value, in case we want None as default

        def pop_table(cfg: TOMLDocument, table: str, default: Any = marker) -> Any:
            try:
                entry = cfg.pop(table)
                if not isinstance(entry, Table):
                    raise UnknownKeyError([table])
            except tomlkit.exceptions.NonExistentKey as e:
                if default is marker:
                    raise MissingTableError(table) from e
                else:
                    entry = default
            return entry

        def pop(table: Table, key: str, valtype: type, default: Any = marker) -> Any:
            try:
                val = table.pop(key)
            except tomlkit.exceptions.NonExistentKey as e:
                if default is marker:
                    raise MissingKeyError(table.display_name, key) from e
                else:
                    val = default
            if not isinstance(val, valtype):
                raise KeyValidationError(
                    table.display_name, key, valtype.__name__, type(val).__name__
                )
            return val

        def pop_ip(table: Table, key: str, valtype: type, default: Any = marker) -> IPv4Address:
            value = pop(table, key, valtype, default)
            try:
                return IPv4Address(gethostbyname(value))
            except (AddressValueError, gaierror) as e:
                raise IpValidationError(table.display_name, key, value) from e

        def pop_angle(table: Table, key: str, valtype: type, default: Any = marker) -> ephem.Angle:
            value = pop(table, key, valtype, default)
            try:
                value = ephem.degrees(radians(value))
            except (ValueError, TypeError) as e:
                raise AngleValidationError(table.display_name, key, value) from e
            if not radians(-180) < value < radians(180):
                raise AngleValidationError(table.display_name, key, value)
            return value

        main = pop_table(config, 'Main')
        self.sat_id = pop(main, 'satellite', str, self.sat_id)
        self.owmid = pop(main, 'owmid', str, self.owmid)
        self.edl_port = pop(main, 'edl_port', int, self.edl_port)
        self.txgain = pop(main, 'txgain', int)

        hosts = pop_table(config, 'Hosts')
        self.radio = pop_ip(hosts, 'radio', str)
        self.station = pop_ip(hosts, 'station', str)
        self.rotator = pop_ip(hosts, 'rotator', str)

        observer = pop_table(config, 'Observer')
        self.lat = pop_angle(observer, 'lat', Number)
        self.lon = pop_angle(observer, 'lon', Number)
        self.alt = pop(observer, 'alt', int)
        self.name = pop(observer, 'name', str)

        self.tle_cache = pop_table(config, 'TleCache', {})
        # validate TLEs
        for key, tle in self.tle_cache.items():
            try:
                ephem.readtle(*tle)
            except (TypeError, ValueError) as e:
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
