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

## Python Utility – *CANb0t Rebooted*

The Python helper has been rewritten from the ground up.  The new
`can_engine.py` focuses on a few core capabilities while retaining the neon
console flair:

1. **Serial logging** – stream frames from the Arduino logger and append
   them to `CANLOG.CSV` while the console offers pause/resume controls.
2. **DBC command transmission** – load a DBC file and encode messages for
   transmission over any python‑can compatible interface.  Any message sent
   or observed can be stored so the exact bytes may be reissued later.
3. **Interactive PID console** – issue OBD‑II PID requests from a menu and
   display decoded responses.
4. **Filtered serial capture** – select messages from the loaded DBC and
   log only matching frames while automatically caching their data bytes.

When sending a message interactively, the helper now inspects `CANLOG.CSV`
and prepopulates each signal with the most recently observed byte values so
common commands can be re‑issued quickly.

Example invocations:

```bash
# Log frames arriving on the default serial port
python can_engine.py serial

# Send a command defined in the DBC
python can_engine.py send landrover2008lr3.dbc DOOR_UNLOCK_CMD --channel can0 DoorID=1 Toggle=1

# Launch the interactive PID console
python can_engine.py pid --channel can0
```

Running `python can_engine.py` with no sub‑command displays a small menu
offering the same actions.

On platforms without native SocketCAN support (for example, Windows), the
utility automatically falls back to python‑can's virtual interface so
commands can be encoded and tested without actual hardware.
