#
# Copyright (c) 2022-2023 Kenny M.
#
# This file is part of UniClOGS Pass Commander 
# (see https://github.com/uniclogs/uniclogs-pass_commander).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

from argparse import ArgumentParser, RawTextHelpFormatter
from textwrap import dedent
from pass_commander.main import main

parser = ArgumentParser(formatter_class=RawTextHelpFormatter)
parser.add_argument('-a', '--action', choices=('run', 'dryrun', 'doppler', 'nextpass'),
    help=dedent("""\
        Which action to have Pass Commander take
        - run: Normal operation
        - dryrun: Simulate the next pass immediately
        - doppler: Show present RX/TX frequencies
        - nextpass: Sleep until next pass and then quit
        Default: '%(default)s'"""),
    default='run')
parser.add_argument('-c', '--config', default="~/.config/OreSat/pass_commander.ini",
    help=dedent("""\
        Path to .ini Config file
        Default: '%(default)s'"""))
parser.add_argument('--tle-cache', default="~/.config/OreSat/tle_cache.json",
    help=dedent("""\
        Path to local JSON TLE cache
        Default: '%(default)s'"""))
parser.add_argument('-e', '--edl-command',
    help=dedent('''\
        Optional EDL command to send periodically during a pass
        Must be hex formatted with no 0x prefix'''))
parser.add_argument('-m', '--mock', action='append', choices=('tx', 'rot', 'con', 'all'),
    help=dedent('''\
        Use a simulated (mocked) external dependency, not the real thing
        - tx: No PTT or EDL bytes sent to flowgraph
        - rot: No actual movement commanded for the rotator
        - con: Don't use network services - TLEs, weather, rot2prog, stationd
        - all: All of the above
        Can be issued multiple times, e.g. '-m tx -m rot' will disable tx and rotator'''))
parser.add_argument('-p', '--pass-count', type=int, default=9999,
    help="Maximum number of passes to operate before shutting down. Default: '%(default)s'")
parser.add_argument('-s', '--satellite',
    help='can be International Designator, Catalog Number, or Name')
parser.add_argument('-t', '--tx-gain', type=int,
    help='Transmit gain, usually between 0 and 100ish')
parser.add_argument('-v', '--verbose', action='count',
    help='Increase verbosity. Not currently implemented')
main(parser.parse_args())
