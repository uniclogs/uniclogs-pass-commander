# UniClOGS Pass Commander
This software controlls the local functions of a [UniClOGS](https://www.oresat.org/technologies/ground-stations) for sending commands to the [OreSat0](https://www.oresat.org/satellites/oresat0) [CubeSat](https://en.wikipedia.org/wiki/CubeSat).

## Major functions
* Tracks satellites using the excellent [ephem](https://rhodesmill.org/pyephem/) module
  * Fetches fresh TLEs from [celestrak.org](https://celestrak.org)
  * Calibrates for atmospheric refraction with local temperature and pressure, fetched via API
* Adapts tracking information to suit az/el rotator limits
* Interacts with [Hamlib rotctld](https://github.com/Hamlib/Hamlib/wiki/Documentation) to command the antenna rotator
* Interacts with [stationd](https://github.com/uniclogs/uniclogs-stationd/tree/python-rewrite) to control amplifiers and station RF path
* Interacts with the [OreSat GNURadio flowgraph](https://github.com/uniclogs/uniclogs-sdr/tree/maint-3.10/flowgraphs) to manage Doppler shifting and to send command packets

## Installing
```sh
git clone https://github.com/uniclogs/uniclogs-pass_commander.git
sudo apt install python3-pip python3-hamlib python3-pydbus python3-requests python3-apscheduler python3-ephem
python3 uniclogs-pass_commander/
```
You should receive instructions for editing a config file. Go do that now.

When your config is all set up, run with `python3 uniclogs-pass_commander/`

Testing without rotctld, stationd and a runing radio flowgraph is not presently supported.
