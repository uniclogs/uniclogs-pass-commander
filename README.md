# UniClOGS Pass Commander
This software controls the local functions of a
[UniClOGS](https://www.oresat.org/technologies/ground-stations) for sending
commands to the [OreSat0](https://www.oresat.org/satellites/oresat0) and
[OreSat0.5](https://www.oresat.org/satellites/oresat0-5)
[CubeSats](https://en.wikipedia.org/wiki/CubeSat).

## Major functions
* Tracks satellites using the excellent [ephem](https://rhodesmill.org/pyephem/)
  module
  * Fetches fresh TLEs from [celestrak.org](https://celestrak.org)
  * Alternatively uses TLEs from a local [Gpredict](https://github.com/csete/gpredict)
    install
  * Calibrates for atmospheric refraction with local temperature and pressure,
    fetched via API from [OpenWeather](https://openweathermap.org/)
* Adapts tracking information to suit az/el rotator limits
* Interacts with [Hamlib rotctld](https://github.com/Hamlib/Hamlib/wiki/Documentation)
  to command the antenna rotator
* Interacts with [stationd](https://github.com/uniclogs/uniclogs-stationd) to
  control amplifiers and station RF path
* Interacts with the [OreSat GNURadio flowgraph](https://github.com/uniclogs/uniclogs-sdr)
  to manage Doppler shifting and to send command packets

## Installing
```sh
git clone https://github.com/uniclogs/uniclogs-pass_commander.git
sudo apt install python3-pip python3-hamlib
pip3 install -e uniclogs-pass_commander[dev]
```

Running `pass-commander --template` will generate a
template configuration file. You should receive instructions for editing it. Go
do that now (see below for detailed description).

When your config is all set up, run with `pass-commander`. See the
`--help` flag for more options. For example `pass-commander -s 60525
-m all -a dryrun`.

Testing without rotctld, stationd and a running radio flowgraph is partially
supported. See the `--mock` flag, especially `-m all`.

## Building
To produce a python package `python -m build`. The result, a wheel, will be in `dist/`.


## Config file
It's [TOML](https://toml.io/en/). There are four primary sections, each with
a set of mandatory configuration keys:
#### [Main]
General operation settings.
* `satellite` (String, optional) - Default satellite ID, either index into TleCache or NORAD ID.
* `owmid` (String, optional) - An API key from [OpenWeatherMap API](https://openweathermap.org/api)
* `edl_port` (int, optional) - Port to listen for
  [EDL commands](https://oresat-c3-software.readthedocs.io/en/latest/edl.html).
  Only open during a pass. Consult
  [oresat-c3-software](https://github.com/oresat/oresat-c3-software) for
  more.
* `txgain` (Integer) - Gain for transmitting. Usually between 0 and 100.

#### [Hosts]
IP addresses for external components.
* `radio` (String) - IP address or hostname of the flowgraph.
* `station` (String) - IP address or hostname of stationd.
* `rotator` (String) - IP address or hostname of rotctld.

#### [Observer]
Physical properties of the ground station.
* `lat` (Float or Integer) - Station latitude in decimal notation. For best results use 3 - 4
  decimal points. See [here](https://xkcd.com/2170/) for more.
* `lon` (Float or Integer) - Station longitude in decimal notation.
* `alt` (Integer) - Station altitude in meters.
* `name` (String) - station name or callsign.

#### [TleCache]
Optional local cache of TLEs. Currently only 3 line TLEs are supported. Format
is:
```
<name>: [
    "<Satellite name>",
    "<TLE line 1>",
    "<TLE line 2>",
]
```
TLE cache entries may be repeated as long as `<name>` is unique. Select which
entry is active by passing `<name>` to the `--satellite` flag.
