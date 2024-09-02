from dataclasses import InitVar, dataclass, field
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path
from typing import Any, Union

import ephem
import tomlkit


class ConfigError(Exception):
    pass


class TleValidationError(ConfigError):
    def __init__(self, name: str, tle: list[str]):
        super().__init__(f'TLE for {name}')
        self.name = name
        self.tle = tle


class IpValidationError(ConfigError):
    def __init__(self, table: str, key: str, value: Any):
        super().__init__(f"'{table}.{key}'")
        self.table = table
        self.key = key
        self.value = value


class KeyValidationError(ConfigError):
    def __init__(self, table: str, key: str, expect: str, actual: str):
        super().__init__(f"'{key}' invalid type {actual}")
        self.table = table
        self.key = key
        self.expect = expect
        self.actual = actual


class TemplateTextError(ConfigError):
    pass


class UnknownKeyError(ConfigError):
    def __init__(self, keys: list[str]):
        super().__init__(' '.join(keys))
        self.keys = keys


class MissingKeyError(ConfigError):
    def __init__(self, table, key):
        super().__init__(f'{table}.{key}')
        self.table = table
        self.key = key


class InvalidTomlError(ConfigError):
    pass


class ConfigNotFoundError(ConfigError):
    pass


@dataclass
class Config:
    path: InitVar[Path]

    # [Main]
    owmid: str = '<open weather map API key>'
    edl: str = '<EDL command to send, hex formatted with no 0x prefix>'
    txgain: int = 47

    # [Hosts]
    radio: IPv4Address = IPv4Address('127.0.0.2')
    station: IPv4Address = IPv4Address('127.0.0.1')
    rotator: IPv4Address = IPv4Address('127.0.0.1')

    # [Observer]
    lat: Union[float, str] = '<latitude in decimal notation>'
    lon: Union[float, str] = '<longitude in decimal notation>'
    alt: Union[int, str] = '<altitude in meters>'
    name: str = '<station name or callsign>'

    # ??? Should these be set from cmdline/config?
    az_cal: int = 0
    el_cal: int = 0

    # Satellite
    sat_id: str = "OreSat0"
    tle_cache: dict[str, list[str]] = field(default_factory=dict)

    # Command line only
    mock: set[str] = field(default_factory=set)
    pass_coutn: int = 9999

    def __post_init__(self, path: Path):
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
            if not isinstance(table, tomlkit.items.Table):
                continue
            for key, value in table.items():
                if isinstance(value, str) and value and value[0] == '<':
                    raise TemplateTextError(f'{name}.{key}')

        def get(cfg: tomlkit.TOMLDocument, table: str, key: str, valtype: type) -> Any:
            try:
                entry = cfg[table]
                if not isinstance(entry, tomlkit.items.Table):
                    raise UnknownKeyError([table])
                val = entry.pop(key)
            except tomlkit.exceptions.NonExistentKey as e:
                raise MissingKeyError(table, key) from e
            if not isinstance(val, valtype):
                raise KeyValidationError(table, key, valtype.__name__, type(val).__name__)
            return val

        def getip(cfg: tomlkit.TOMLDocument, table: str, key: str, valtype: type) -> IPv4Address:
            value = get(cfg, table, key, valtype)
            try:
                return IPv4Address(value)
            except AddressValueError as e:
                raise IpValidationError('Hosts', key, value) from e

        # Mandatory keys
        self.owmid = get(config, 'Main', 'owmid', str)
        self.edl = get(config, 'Main', 'edl', str)
        self.txgain = get(config, 'Main', 'txgain', int)

        self.radio = getip(config, 'Hosts', 'radio', str)
        self.station = getip(config, 'Hosts', 'station', str)
        self.rotator = getip(config, 'Hosts', 'rotator', str)

        self.lat = get(config, 'Observer', 'lat', float)
        self.lon = get(config, 'Observer', 'lon', float)
        self.alt = get(config, 'Observer', 'alt', int)
        self.name = get(config, 'Observer', 'name', str)

        # TLE cache is optional
        self.tle_cache = config.pop('TleCache', {})
        for key, tle in self.tle_cache.items():
            try:
                ephem.readtle(*tle)  # validate TLEs
            except (TypeError, ValueError) as e:
                raise TleValidationError(key, tle) from e

        # Ensure there's no extra keys
        extra = ['Main.' + k for k in config.pop('Main')]
        extra.extend('Hosts.' + k for k in config.pop('Hosts'))
        extra.extend('Observer.' + k for k in config.pop('Observer'))
        extra.extend(k for k in config)
        if extra:
            raise UnknownKeyError(extra)

    @classmethod
    def template(cls, path: Path):
        config = tomlkit.document()
        config.add(tomlkit.comment("Be sure to replace all <hint text> including angle brackets!"))

        main = tomlkit.table()
        main['owmid'] = cls.owmid
        main['edl'] = cls.edl
        main['txgain'] = cls.txgain

        hosts = tomlkit.table()
        hosts['radio'] = str(cls.radio)
        hosts['station'] = str(cls.station)
        hosts['rotator'] = str(cls.rotator)

        observer = tomlkit.table()
        observer['lat'] = cls.lat
        observer['lon'] = cls.lon
        observer['alt'] = cls.alt
        observer['name'] = cls.name

        config['Main'] = main
        config['Hosts'] = hosts
        config['Observer'] = observer

        path = path.expanduser()
        if path.exists():
            raise FileExistsError

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(config))
