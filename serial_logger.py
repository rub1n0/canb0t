import argparse
import re
import time
from typing import Dict
import threading
import sys

import serial

PID_NAMES: Dict[int, str] = {
    0x0C: "ENGINE_RPM",
    0x0D: "VEHICLE_SPEED",
    0x11: "THROTTLE_POSITION",
    0x05: "COOLANT_TEMP",
}

PATTERN = re.compile(r"ID: 0x([0-9A-F]+)\s+DLC:(\d+)\s+Data:(.*)")


def log_serial_frames(port: str, baudrate: int) -> None:
    paused = False
    stop = False

    def control_loop() -> None:
        nonlocal paused, stop
        print("Type 'p' then Enter to pause, 'r' to resume, or 'q' to quit.")
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "p":
                paused = True
                print("Logging paused. Type 'r' to resume.")
            elif cmd == "r":
                paused = False
                print("Logging resumed.")
            elif cmd == "q":
                stop = True
                break

    threading.Thread(target=control_loop, daemon=True).start()

    with serial.Serial(port, baudrate, timeout=1) as ser, open("CANLOG.CSV", "a") as log:
        if log.tell() == 0:
            log.write("timestamp_ms,id,dlc,data\n")
        try:
            while not stop:
                if paused:
                    time.sleep(0.1)
                    continue
                line = ser.readline().decode("ascii", errors="ignore").strip()
                match = PATTERN.match(line)
                if not match:
                    continue
                can_id = match.group(1)
                dlc = int(match.group(2))
                data_str = match.group(3).strip()
                data_bytes = [int(b, 16) for b in data_str.split() if b]

                id_field = can_id
                if data_bytes and data_bytes[0] == 0x41 and len(data_bytes) > 1:
                    pid = data_bytes[1]
                    if pid in PID_NAMES:
                        id_field = PID_NAMES[pid]
                ts_ms = int(time.time() * 1000)
                log.write(
                    f"{ts_ms},{id_field},{dlc},{' '.join(f'{b:02X}' for b in data_bytes)}\n"
                )
                log.flush()
        except KeyboardInterrupt:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Log CAN frames from serial to CSV")
    parser.add_argument("--port", default="COM3", help="Serial port, default COM3")
    parser.add_argument("--baudrate", type=int, default=115200, help="Baud rate, default 115200")
    args = parser.parse_args()
    log_serial_frames(args.port, args.baudrate)


if __name__ == "__main__":
    main()
