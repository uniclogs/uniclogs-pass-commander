import logging
from argparse import ArgumentParser, Namespace, RawTextHelpFormatter
from pathlib import Path
from textwrap import dedent

from skyfield.api import E, N, wgs84

from . import config, mock
from .commander import Commander

logger = logging.getLogger(__name__)


def handle_args() -> Namespace:  # noqa: D103
    parser = ArgumentParser(formatter_class=RawTextHelpFormatter)
    parser.add_argument(
        "-a",
        "--action",
        choices=("run", "dryrun", "nextpass"),
        help=dedent(
            """\
            Which action to have Pass Commander take
            - run: Normal operation
            - dryrun: Simulate the next pass immediately
            - nextpass: Sleep until next pass and then quit
            Default: '%(default)s'"""
        ),
        default="run",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=config.Config.dir / "pass_commander.toml",
        type=Path,
        help=dedent(
            """\
            Path to .toml config file. If dir will assume 'pass_commander.toml' in that dir
            Default: '%(default)s'"""
        ),
    )
    parser.add_argument(
        "--template",
        action="store_true",
        help="Generate a config template at the path specified by --config",
    )
    parser.add_argument(
        "-e",
        "--edl-port",
        type=int,
        default=10025,
        help="Port to listen for EDL packets on, default: %(default)s",
    )
    parser.add_argument(
        "-m",
        "--mock",
        action="append",
        choices=("tx", "rot", "con", "tle", "all"),
        help=dedent(
            """\
            Use a simulated (mocked) external dependency, not the real thing
            - tx: No PTT or EDL bytes sent to flowgraph
            - rot: No actual movement commanded for the rotator
            - con: Don't use network services - weather, rot2prog, stationd
            - tle: Only use locally saved TLEs, don't fetch from the internet (CelesTrak)
            - all: All of the above
            Can be issued multiple times, e.g. '-m tx -m rot' will disable tx and rotator"""
        ),
    )
    parser.add_argument(
        "--pass-count",
        type=int,
        default=9999,
        help="Maximum number of passes to operate before shutting down. Default: '%(default)s'",
    )
    parser.add_argument(
        "-s",
        "--satellite",
        help=dedent(
            """\
            Can be International Designator, Catalog Number, or Name.
            If `--mock con` is specified will search local TLE cache and Gpredict cache
            """
        ),
    )
    parser.add_argument(
        "-t", "--tx-gain", type=int, help="Transmit gain, usually between 0 and 100ish"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="Output additional debugging information",
    )
    parser.add_argument(
        "--temperature-limit",
        type=float,
        help="Temperature in Celsius of the station above which prevents a pass from running",
    )
    parser.add_argument(
        "-p",
        "--point",
        help="Point antenna at a given coordinate and start a pass. Format: <lat>,<lon> in decimal",
    )
    return parser.parse_args()


def _cfgerr(args: Namespace, msg: str) -> None:
    # This function is always called from an exception handler
    logger.debug("Config error", exc_info=True)  # noqa: LOG014
    logger.error("In '%s': %s", args.config, msg)


def main() -> None:  # noqa: D103 C901 PLR0912 PLR0915
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)-25s: %(message)s'
    )

    args = handle_args()
    if args.config.is_dir():
        args.config /= "pass_commander.toml"

    if args.template:
        try:
            config.Config.template(args.config)
        except FileExistsError:
            _cfgerr(args, 'delete existing file before creating template')
        else:
            logger.info("Config template generated at '%s'", args.config)
            logger.info("Edit '%s' <template text> before running again", args.config)
        return

    try:
        conf = config.Config(args.config)
    except config.ConfigNotFoundError as e:
        _cfgerr(
            args,
            f"the file is missing ({type(e.__cause__).__name__}). Initialize using --template",
        )
    except config.InvalidTomlError as e:
        _cfgerr(args, f"there is invalid toml: {e}\nPossibly an unquoted string?")
    except config.MissingKeyError as e:
        _cfgerr(args, f"required key '{e.table}.{e.key}' is missing")
    except config.TemplateTextError as e:
        _cfgerr(args, f"key '{e}' still has template text. Replace <angle brackets>")
    except config.UnknownKeyError as e:
        _cfgerr(args, f"remove unknown keys: {' '.join(e.keys)}")
    except config.KeyValidationError as e:
        _cfgerr(args, f"key '{e.table}.{e.key}' has invalid type {e.actual}, expected {e.expect}")
    except config.IpValidationError as e:
        _cfgerr(args, f"contents of '{e.table}.{e.key}' is not a valid IP")
    except config.TleValidationError as e:
        _cfgerr(args, f"TLE '{e.name}' is invalid: {e.__cause__}")
    else:
        conf.mock = set(args.mock or [])
        if 'all' in conf.mock:
            conf.mock = {'tx', 'rot', 'con', 'tle'}
        # Favor command line values over config file values
        conf.txgain = args.tx_gain or conf.txgain
        conf.sat_id = args.satellite or conf.sat_id
        if not conf.sat_id:
            logger.error(
                "No satellite specified. Set on command line (see --help) or in config file."
            )
            return
        conf.pass_count = args.pass_count
        conf.temp_limit = args.temperature_limit or conf.temp_limit

        mock_edl = None
        mock_flowgraph = None
        mock_stationd = None
        mock_rotator = None

        if 'con' in conf.mock:
            # Radio mock
            conf.edl = ("127.0.0.1", conf.edl[1])
            mock_edl = mock.Edl()
            conf.edl_dest = mock_edl.addr
            mock_edl.start()
            mock_flowgraph = mock.Flowgraph()
            conf.flowgraph = mock_flowgraph.addr
            mock_flowgraph.start()
            # Tracker mock
            conf.owmid = ''

        if 'tx' in conf.mock:
            mock_stationd = mock.Stationd()
            conf.station = mock_stationd.addr
            mock_stationd.start()

        if 'rot' in conf.mock:
            mock_rotator = mock.PtyRotator(pulses_per_degree=1)
            conf.rotator = mock_rotator.client_path

        commander = Commander(conf)

        try:
            if args.point is not None:
                lat, lon = args.point.split(',')
                commander.point(wgs84.latlon(float(lat) * N, float(lon) * E, 50))
            elif args.action == 'run':
                commander.autorun(count=conf.pass_count)
            elif args.action == 'dryrun':
                commander.dryrun()
            elif args.action == 'nextpass':
                sat, np = commander.sleep_until_next_pass()
                logger.info('Slept for pass %s by sat %s', np, sat)
            else:
                logger.info("Unknown action: %s", args.action)
        finally:
            # TODO: context manager/closeable for mocks?
            if mock_edl is not None:
                mock_edl.close()
            if mock_flowgraph is not None:
                mock_flowgraph.close()
            if mock_stationd is not None:
                mock_stationd.close()
            if mock_rotator is not None:
                mock_rotator.close()
