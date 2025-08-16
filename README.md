# canb0t

canb0t is a retro-styled CAN bus logger for ELM327-compatible OBD-II adapters. It can sniff raw CAN traffic or poll a set of common PIDs, storing results in a CSV file with a flashy hacker console.

## Features
- Initializes an ELM327 adapter and logs every command and response to a debug file
- **Sniff mode** captures raw CAN frames with a live dashboard showing frame count, unique IDs, and capture rate
- **PID mode** queries selected PIDs like RPM, speed, throttle, and coolant temperature
- Saves all frames with timestamps to a CSV output file
- Rich-based neon console with random one-liners for style

## Installation
1. Ensure Python 3.11+ is installed
2. Install dependencies:
   ```bash
   pip install rich python-dotenv
   ```
3. Optionally create a virtual environment before installing

## Setup
- The script reads configuration from environment variables or command-line flags. Place values in a `.env` file or export them before running.
  - `IP` – adapter IP address (default `192.168.0.10`)
  - `PORT` – adapter TCP port (default `35000`)
  - `OUTFILE` – CSV output file (default `can_log.csv`)
  - `LOGFILE` – debug log file (default `canb0t.log`)
  - `MODE` – `sniff` or `pid` (default `sniff`)

## Usage
Show help:
```bash
python canb0t.py --help
```

Sniff raw frames and log debug output:
```bash
python canb0t.py --ip 192.168.0.10 --port 35000 --mode sniff --logfile debug.log
```

Poll for PID data:
```bash
python canb0t.py --mode pid --outfile pid_data.csv
```

Captured frames are written to the CSV file and debug messages go to the log file, assisting with OBD-II connection troubleshooting.

## SparkFun RedBoard with CAN-Bus Shield

An Arduino sketch (`canb0t_redboard.ino`) is included for running canb0t on a SparkFun RedBoard paired with the [SparkFun CAN-Bus Shield](https://www.sparkfun.com/products/13262). The sketch uses the MCP2515 controller to sniff raw frames or query a few common OBD-II PIDs.

1. Install the [MCP_CAN library](https://github.com/coryjfowler/MCP_CAN_lib) in the Arduino IDE.
2. Open `canb0t_redboard.ino`.
3. Set `PID_MODE` to `true` to enable PID polling; otherwise, the sketch logs all observed frames.
4. Upload to the board and open the serial monitor at 115200 baud to view the log.
