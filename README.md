# UniClOGS Pass Commander
This software controls the local functions of a
[UniClOGS](https://www.oresat.org/technologies/ground-stations) ground station
for sending commands to [CubeSats](https://en.wikipedia.org/wiki/CubeSat), as
used with the [OreSat0](https://www.oresat.org/satellites/oresat0)
and [OreSat0.5](https://www.oresat.org/satellites/oresat0-5) missions.

## Major functions
* Tracks satellites using the excellent [Skyfield](https://rhodesmill.org/skyfield/)
  module
  * Fetches fresh TLEs from [celestrak.org](https://celestrak.org)
  * Alternatively uses TLEs from a local [Gpredict](https://github.com/csete/gpredict)
    install
  * Calibrates for atmospheric refraction with local temperature and pressure,
    fetched via API from [OpenWeather](https://openweathermap.org/)
* Adapts tracking information to suit az/el rotator limits
* Interacts with [Alfa Rot2Prog Controller](http://alfaradio.ca/) via
  [Rot2prog](https://pypi.org/project/rot2prog/) to command the antenna rotator
* Interacts with [stationd](https://github.com/uniclogs/uniclogs-stationd) to
  control amplifiers and station RF path
* Interacts with the [OreSat GNURadio flowgraph](https://github.com/uniclogs/uniclogs-sdr)
  to manage Doppler shifting and to send command packets

## Installing
Requires Linux with Python 3.11 or greater.

```sh
git clone https://github.com/uniclogs/uniclogs-pass-commander.git
sudo apt install python3-pip
pip3 install -e uniclogs-pass-commander[dev]
```

Running `pass-commander --template` will generate a
template configuration file. You should receive instructions for editing it. Go
do that now (see below for detailed description).

When your config is all set up, run with `pass-commander`. See the `--help` flag
for more options. Initially you'll not have any saved TLEs so either find one
for your satellite of interest and add it to `TleCache` in `pass_commander.toml`
or run without the `--mock tle` flag to download one locally:
```sh
pass-commander --satellite 60525 --action dryrun -m tx -m con -m rot
```
After that the `--mock all` flag can be used for brevity:
```sh
pass-commander --satellite 60525 --action dryrun --mock all
```

Testing without rotctld, stationd and a running radio flowgraph is partially
supported. See the `--mock` flag, especially `-m all`.

### Testing
To verify that the repo is set up correctly run the tests with `pytest`

## Building
To produce a python package `python -m build`. The result, a wheel, will be in `dist/`.


## Config file
It's [TOML](https://toml.io/en/). There are four primary sections, each with
a set of mandatory configuration keys:
#### [Main]
General operation settings.
* `satellite` (String, optional) - Default satellite ID, either index into TleCache or NORAD ID.
* `minimum-pass-elevation` (Float or Integer, optional) - Minimum elevation that `satellite` must
  rise above to be considered for a pass. Default: 15°
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
* `temperature-limit` (Float or Integer, optional) - Temperature in Celsius above which stops a
  pass from being run to protect the hardware. Default: 40°C

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

## Release Process

Releases are managed through an automated workflow using Github Actions. The
automation is triggered when a release is published on Github.

### Creating a Release

1.  Navigate to this project's "Releases" page
2.  Click "Draft a new release"
3.  Click "Tag: Select tag" and click on the "Create new tag" button
4.  Add a tag following the [SemVer](https://semver.org/) standard
    -   e.g. `v1.2.3`
5.  Ensure that Target button is pointing at the `main` branch
6.  Add all necessary details about the release under "Release notes"
7.  Once everything looks good, click the "Publish release" button

Step 7 will trigger the `pypi.yml` workflow and the new release will be
available on pypi.org.

### Post-Release

Once a new release has been created and is available on pypi.org, smoke test
the release to ensure it runs as expected.

```sh
pip install your-package==X.Y.Z
```
