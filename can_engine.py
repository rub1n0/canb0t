"""Master CAN bus decoding engine consolidating log parsing, DBC building,
serial logging and command transmission.

This module combines the previous standalone scripts into a single
`CANEngine` class.  It can:
* parse log files produced by the Arduino logger
* summarise and decode OBD-II frames
* build a DBC file from a log
* log frames from a serial port
* load the generated DBC and send commands based on it

Example:
    engine = CANEngine()
    engine.load_dbc('output.dbc')
    engine.send_command('DOOR_UNLOCK_CMD')
"""
from __future__ import annotations

import argparse
import csv
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    import serial  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    serial = None  # type: ignore

try:
    import cantools  # type: ignore
    import can  # python-can
except Exception:  # pragma: no cover - optional dependency
    cantools = None  # type: ignore
    can = None  # type: ignore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CANFrame:
    """Simple representation of a CAN frame."""

    timestamp_ms: int
    can_id: int
    dlc: int
    data: List[int]


PID_NAMES: Dict[int, str] = {
    0x0C: "ENGINE_RPM",
    0x0D: "VEHICLE_SPEED",
    0x11: "THROTTLE_POSITION",
    0x05: "COOLANT_TEMP",
}

# Known OBD-II PID signal definitions: pid -> (name, length_bits, factor, offset, unit)
PID_SIGNALS: Dict[int, tuple[str, int, float, float, str]] = {
    0x0C: ("EngineRPM", 16, 0.25, 0.0, "rpm"),
    0x0D: ("VehicleSpeed", 8, 1.0, 0.0, "km/h"),
    0x11: ("ThrottlePosition", 8, 100.0 / 255.0, 0.0, "%"),
    0x05: ("CoolantTemp", 8, 1.0, -40.0, "°C"),
}

# Known message names for specific CAN IDs
MESSAGE_NAMES: Dict[int, str] = {
    0x5F1: "DOOR_UNLOCK_CMD",
    0x5FB: "DOOR_LOCK_CMD",
}

# Neon-soaked console styling for that 1980's techno-thriller vibe
NEON_MAGENTA = "\033[95m"
NEON_CYAN = "\033[96m"
NEON_GREEN = "\033[92m"
RESET = "\033[0m"

BANNER = f"""
{NEON_MAGENTA}
  ____   _    _   _ ____   ___ _____ 
 / ___| / \\  | \\ | | __ ) / _ \\_   _|
| |    / _ \\ |  \\| |  _ \\| | | || |  
| |___/ ___ \\| |\\  | |_) | |_| || |  
 \\____/_/   \\_\\_| \\_|____/ \\___/ |_|
{RESET}
"""


def neon(text: str, color: str = NEON_CYAN) -> str:
    """Wrap text in eye-searing ANSI colors."""
    return f"{color}{text}{RESET}"


# ---------------------------------------------------------------------------
# CAN engine implementation
# ---------------------------------------------------------------------------


class CANEngine:
    """Master CAN bus decoding engine."""

    def __init__(self) -> None:
        self.db = None  # type: ignore

    # -- Log parsing -----------------------------------------------------
    def parse_log(self, path: str) -> List[CANFrame]:
        frames: List[CANFrame] = []
        with open(path, newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or row[0] == "timestamp_ms":
                    continue
                ts = int(row[0])
                can_id = int(row[1], 16) if row[1].startswith("0x") else int(row[1], 16)
                dlc = int(row[2])
                data_bytes = [int(byte, 16) for byte in row[3].split()]
                frames.append(CANFrame(ts, can_id, dlc, data_bytes))
        return frames

    def decode_obd_pid(self, frame: CANFrame) -> Optional[str]:
        if not frame.data:
            return None
        if frame.data[0] == 0x41 and len(frame.data) >= 3:
            pid = frame.data[1]
            if pid == 0x0C and len(frame.data) >= 4:
                rpm = ((frame.data[2] * 256) + frame.data[3]) / 4
                return f"Engine RPM: {rpm}"
            if pid == 0x0D and len(frame.data) >= 3:
                speed = frame.data[2]
                return f"Vehicle Speed: {speed} km/h"
            if pid == 0x11 and len(frame.data) >= 3:
                throttle = frame.data[2] * 100 / 255
                return f"Throttle Position: {throttle:.1f}%"
            if pid == 0x05 and len(frame.data) >= 3:
                temp = frame.data[2] - 40
                return f"Coolant Temp: {temp} °C"
            return f"PID 0x{pid:02X} data: {' '.join(f'{b:02X}' for b in frame.data[2:])}"
        return None

    # -- DBC building ----------------------------------------------------
    def build_dbc(self, frames: List[CANFrame], output_path: str) -> None:
        from collections import defaultdict
        import os
        import re

        frames_by_id: Dict[int, List[CANFrame]] = defaultdict(list)
        for f in frames:
            frames_by_id[f.can_id].append(f)

        existing_ids = set()
        mode = "w"
        if os.path.exists(output_path):
            with open(output_path, "r") as dbc:
                for line in dbc:
                    m = re.match(r"^BO_\s+(\d+)\s+", line)
                    if m:
                        existing_ids.add(int(m.group(1)))
            mode = "a"

        with open(output_path, mode) as dbc:
            if mode == "w":
                dbc.write('VERSION "generated by CANEngine"\n\n')
                dbc.write('NS_ :\n\n')
                dbc.write('BS_:\n\n')
                dbc.write('BU_: Vector__XXX\n\n')
            else:
                dbc.write("\n")

            for can_id, msgs in sorted(frames_by_id.items()):
                if can_id in existing_ids:
                    continue
                dlc = max(f.dlc for f in msgs)
                name = MESSAGE_NAMES.get(can_id, f"MSG_{can_id:03X}")
                dbc.write(f"BO_ {can_id} {name}: {dlc} Vector__XXX\n")

                pids = {f.data[1] for f in msgs if len(f.data) >= 2 and f.data[0] == 0x41}
                if pids:
                    dbc.write(" SG_ Service : 0|8@1+ (1,0) [0|255] \"\" Vector__XXX\n")
                    dbc.write(" SG_ PID M : 8|8@1+ (1,0) [0|255] \"\" Vector__XXX\n")
                    for pid in sorted(pids):
                        if pid in PID_SIGNALS:
                            name, size, factor, offset, unit = PID_SIGNALS[pid]
                            start_bit = 16
                            max_raw = (1 << size) - 1
                            min_val = offset
                            max_val = max_raw * factor + offset
                            dbc.write(
                                f" SG_ {name} m{pid}: {start_bit}|{size}@1+ ({factor},{offset}) [{min_val}|{max_val}] \"{unit}\" Vector__XXX\n"
                            )
                        else:
                            dbc.write(
                                f" SG_ PID_{pid:02X} m{pid}: 16|8@1+ (1,0) [0|255] \"\" Vector__XXX\n"
                            )
                else:
                    for i in range(dlc):
                        dbc.write(
                            f" SG_ BYTE{i} : {i*8}|8@1+ (1,0) [0|255] \"\" Vector__XXX\n"
                        )
                dbc.write("\n")

    # -- Serial logging --------------------------------------------------
    def log_serial_frames(self, port: str, baudrate: int) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed")

        import re
        pattern = re.compile(r"ID: 0x([0-9A-F]+)\s+DLC:(\d+)\s+Data:(.*)")

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

        import sys

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
                    match = pattern.match(line)
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

    # -- DBC loading and command sending ---------------------------------
    def load_dbc(self, path: str) -> None:
        if cantools is None:
            raise RuntimeError("cantools is required to load DBC files")
        self.db = cantools.database.load_file(path)

    def send_command(self, message: str, channel: str = "can0", **signals: float) -> None:
        """Encode and send a command defined in the loaded DBC."""
        if cantools is None or can is None:
            raise RuntimeError("cantools and python-can are required to send commands")
        if self.db is None:
            raise RuntimeError("DBC not loaded")

        msg = self.db.get_message_by_name(message)
        data = msg.encode(signals)
        bus = can.interface.Bus(channel=channel, bustype="socketcan")
        bus.send(can.Message(arbitration_id=msg.frame_id, data=data))

    def send_pid_request(self, pid: int, channel: str = "can0") -> None:
        """Send a simple OBD-II PID request frame."""
        if can is None:
            raise RuntimeError("python-can is required to send PID requests")
        data = bytes([0x02, 0x01, pid, 0x00, 0x00, 0x00, 0x00, 0x00])
        bus = can.interface.Bus(channel=channel, bustype="socketcan")
        bus.send(can.Message(arbitration_id=0x7DF, data=data))

    def interactive_menu(self, channel: str = "can0") -> None:
        """Interactive menu allowing the user to send PID requests."""
        if can is None:
            msg = "\n".join(
                [
                    "╔════════════════════════════════════════════════════════════╗",
                    "║  python-can module not detected!                          ║",
                    "║  Install it with: pip install python-can                  ║",
                    "╚════════════════════════════════════════════════════════════╝",
                ]
            )
            print(neon(msg, NEON_MAGENTA))
            return
        while True:
            print(neon("\nSelect PID to request:", NEON_MAGENTA))
            for idx, (pid, name) in enumerate(PID_NAMES.items(), start=1):
                print(neon(f"{idx}. {name} (0x{pid:02X})"))
            print(neon("0. EXIT", NEON_MAGENTA))
            choice = input("[PID] > ")
            if choice == "0":
                break
            try:
                pid = list(PID_NAMES.keys())[int(choice) - 1]
            except (ValueError, IndexError):
                print(neon("Invalid selection", NEON_MAGENTA))
                continue
            self.send_pid_request(pid, channel)
            print(neon(f"Sent request for {PID_NAMES[pid]}", NEON_GREEN))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Master CAN bus decoding engine")
    sub = parser.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="Parse a CAN log CSV")
    p_parse.add_argument("log")

    p_build = sub.add_parser("builddbc", help="Build DBC from log")
    p_build.add_argument("log")
    p_build.add_argument("output")

    p_log = sub.add_parser("serial", help="Log frames from serial port")
    p_log.add_argument("port")
    p_log.add_argument("baudrate", type=int, default=115200)

    p_send = sub.add_parser("send", help="Send command from DBC")
    p_send.add_argument("dbc")
    p_send.add_argument("message")
    p_send.add_argument("signals", nargs="*", help="Signal=value pairs")
    p_send.add_argument("--channel", default="can0")

    p_menu = sub.add_parser("menu", help="Interactive menu to send PID requests")
    p_menu.add_argument("--channel", default="can0")

    args = parser.parse_args()
    engine = CANEngine()
    print(BANNER)

    if args.cmd == "parse":
        print(neon(">> INITIATING LOG PARSE SEQUENCE <<", NEON_MAGENTA))
        frames = engine.parse_log(args.log)
        for f in frames[:10]:
            decoded = engine.decode_obd_pid(f)
            if decoded:
                print(neon(f"[{f.timestamp_ms}] 0x{f.can_id:03X} :: {decoded}", NEON_GREEN))
    elif args.cmd == "builddbc":
        print(neon(">> ASSEMBLING DBC MATRIX <<", NEON_MAGENTA))
        frames = engine.parse_log(args.log)
        engine.build_dbc(frames, args.output)
        print(neon(f"DBC WRITTEN TO {args.output}", NEON_GREEN))
    elif args.cmd == "serial":
        engine.log_serial_frames(args.port, args.baudrate)
    elif args.cmd == "send":
        print(neon(">> TRANSMISSION COMMENCING <<", NEON_MAGENTA))
        engine.load_dbc(args.dbc)
        signal_values = {}
        for pair in args.signals:
            if "=" not in pair:
                continue
            name, val = pair.split("=", 1)
            signal_values[name] = float(val)
        engine.send_command(args.message, args.channel, **signal_values)
        print(neon(">> TRANSMISSION COMPLETE <<", NEON_GREEN))
    elif args.cmd == "menu":
        engine.interactive_menu(args.channel)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
