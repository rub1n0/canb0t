# canb0t

## Overview

This repository contains two complementary pieces of tooling for capturing and analysing traffic on a Controller Area Network (CAN):

- **`canb0t_redboard/`** – An Arduino sketch that turns a SparkFun RedBoard (or any ATmega328P-compatible board) paired with the SparkFun CAN-Bus Shield into a stand-alone CAN logger that stores frames on an SD card.
- **`canrx_tool.py`** – A Python 3 command line utility that assists with live capture, replay, and quick exploration of CAN frames via a serial adapter or existing CSV logs.

The codebase has been reviewed to ensure that no secrets, credentials, private keys, access tokens, or other sensitive personal data are stored in the source tree. Configuration defaults such as serial port names and baud rates are generic placeholders and safe to keep under version control.

## Repository layout

| Path | Description |
| ---- | ----------- |
| `canb0t_redboard/canb0t_redboard.ino` | Arduino sketch for on-vehicle CAN sniffing and optional OBD-II PID polling. |
| `canrx_tool.py` | Menu-driven helper for capturing, replaying, and inspecting CAN frames from a computer. |
| `canlog.csv` | Example CSV header illustrating the log format used by the logger and tooling. |

## Firmware: SparkFun RedBoard CAN logger

The Arduino sketch initialises the CAN shield at 500 kbps, logs every frame it receives to both the serial console and an SD card, and optionally polls common OBD-II PIDs. Key behaviour:

- Logs frames to `canlog.csv` with the header `timestamp_ms,id,dlc,data`.
- Supports two operating modes selected by the `PID_MODE` constant:
  - **Sniff mode** (`false`): passively records all CAN frames.
  - **PID mode** (`true`): periodically sends requests for RPM, vehicle speed, throttle position, and coolant temperature.
- Writes human-readable output to the serial terminal at 115200 baud.

### Hardware requirements

- SparkFun RedBoard or Arduino Uno-compatible device.
- SparkFun CAN-Bus Shield (MCP2515 + MCP2551).
- MicroSD card formatted as FAT/FAT32.
- Optional: vehicle OBD-II DLC for PID polling.

### Building and uploading

1. Install the Arduino IDE and add the SparkFun CAN-Bus Shield libraries (`Canbus`, `mcp2515`, etc.).
2. Copy `canb0t_redboard/canb0t_redboard.ino` into your Arduino sketchbook.
3. Adjust the `PID_MODE` constant if you want to switch between sniffing and PID polling.
4. Select the correct board and serial port, then upload the sketch.
5. Open the Serial Monitor at 115200 baud to observe live traffic.

## Python CAN RX Tool (`canrx_tool.py`)

The Python script provides a lightweight terminal UI for capturing frames from a serial device, replaying CSV logs, and experimenting with simple CAN workflows. It uses only the Python standard library and optional third-party modules when available.

### Features

- Serial capture with CSV logging and hotkeys for pausing, filtering, and statistics.
- CSV replay with configurable timing and looping.
- Optional live PID console (requires `python-can`).
- Persistent profile file (`.canrx_profile.json`) storing user preferences.

### Installation

1. Ensure Python 3.8 or newer is installed.
2. (Optional) Install additional dependencies:
   ```bash
   pip install pyserial python-can cantools
   ```

### Usage

Launch the interactive menu:

```bash
python canrx_tool.py
```

Start directly in capture or replay mode:

```bash
python canrx_tool.py --capture
python canrx_tool.py --replay
```

CSV logs follow the schema `timestamp_ms,id_hex,dlc,data_hex`. The default filenames can be changed from the Settings menu and are saved to `.canrx_profile.json`.

### Safety and data handling

- Review and clear `.canrx_profile.json` if it contains environment-specific details you do not wish to keep in source control.
- When sharing captured CAN logs, remove any data that could identify individuals or proprietary systems.

## Development

This repository currently does not include automated tests. Contributions are welcome; please open an issue or submit a pull request describing proposed changes.

## License

Specify your project licence here (e.g., MIT, Apache-2.0). If none is chosen yet, consider adding one to clarify usage rights.

