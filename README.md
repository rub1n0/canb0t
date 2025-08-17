# canb0t

Arduino sketch for logging CAN bus traffic on a SparkFun RedBoard with the SparkFun CAN-Bus Shield. The sketch writes all CAN frames and basic OBD-II PID responses to a microSD card.

## Features
- Initializes the MCP2515 CAN controller and SD card
- Optional PID polling for RPM, speed, throttle and coolant temperature
- Logs every frame with timestamp to `canlog.csv` on the shield's microSD card
- Mirrors frames over the serial port at 115200 baud

## Setup
1. Install the [MCP_CAN library](https://github.com/coryjfowler/MCP_CAN_lib) and the built-in SD library in the Arduino IDE.
2. Assemble the SparkFun CAN-Bus Shield on the RedBoard and insert a microSD card.
3. Open `canb0t_redboard.ino` in the Arduino IDE.
4. Set `PID_MODE` to `true` to enable PID polling or `false` to sniff raw frames.
5. Upload to the board and open the serial monitor at 115200 baud to view live output.

## SD Logging
When running, the sketch creates `canlog.csv` on the microSD card with lines formatted as:

```
timestamp_ms,id,dlc,data
1234,1AB,8,00 FF AA BB CC DD EE FF
```

Each line contains the millisecond timestamp, CAN identifier, data length code, and hex data bytes.

## Master CAN Engine
All of the helper Python scripts have been consolidated into
`can_engine.py`, a single utility that can parse logs, build a DBC file,
stream frames from a serial port and even transmit commands using a CAN
interface.

The console interface embraces a retro techno‑thriller aesthetic with
ANSI neon coloring, ASCII art banners, progress bars and time‑stamped log
lines to make every session feel like a scene from *WarGames*.

Typical usage:

```bash
# Parse and display decoded OBD-II frames from a log
python can_engine.py parse CANLOG.CSV

# Build or extend a DBC file from a log
python can_engine.py builddbc CANLOG.CSV landrover2008lr3.dbc

# Log frames arriving on the default serial port
python can_engine.py serial

# Send a command defined in the DBC (message optional)
python can_engine.py send landrover2008lr3.dbc DOOR_UNLOCK_CMD --channel can0
# omitting the message name will prompt for available messages and signals
```

On platforms without native SocketCAN support (for example, Windows),
the engine automatically falls back to python-can's virtual interface so
commands can be encoded and tested without actual hardware.

The generated `landrover2008lr3.dbc` can still be used with common CAN analysis
tools for further exploration.

Running `python can_engine.py` with no arguments now launches an
interactive menu allowing you to choose from the above functions.

### Interactive Menu Items

The main menu presents numbered options. Enter the number of the desired
action or `0` to exit:

1. **Parse CAN log** – Prompts for the path to a log file, decodes its
   frames and prints the first few interpreted OBD‑II signals.
2. **Build DBC from log** – Requests a log file and destination path, then
   constructs a DBC file describing observed frames.
3. **Log frames from serial port** – Asks for the serial port (defaults to
   COM3) and optional baud rate to record live traffic to the console.
4. **Send command from DBC** – Loads a specified DBC, presents the available
   message names for selection and prompts for each signal value before
   transmitting the command on a chosen channel.
5. **Interactive PID menu** – Opens a submenu listing common OBD‑II PIDs
   that can be requested repeatedly; choose `0` within this submenu to
   return to the main menu.

### Examples

#### Send Command From DBC

The send command can be executed directly or through the interactive menu.

```bash
# Direct invocation specifying the message to transmit
python can_engine.py send landrover2008lr3.dbc DOOR_UNLOCK_CMD --channel can0

# Let the utility prompt for the message and signal values
python can_engine.py
> 4
DBC path: landrover2008lr3.dbc
Channel [can0]:
Select message: 1) DOOR_UNLOCK_CMD
SIGNAL DoorID [0-1]: 1
SIGNAL Toggle   [0-1]: 1
TRANSMISSION COMPLETE
```

#### Interactive PID Menu

Launch the main program and choose the interactive PID option to request
repeated OBD‑II queries.

```bash
python can_engine.py
> 5
Channel [can0]:
1) Engine RPM
2) Vehicle Speed
3) Throttle Position
> 1
ENGINE RPM: 3120
```

Entering `0` in the PID submenu returns to the main menu when finished.
