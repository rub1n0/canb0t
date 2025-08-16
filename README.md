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
