#!/usr/bin/env python3
"""Lightweight CAN-bus reverse engineering tool.

This module provides a command line interface ``canrx`` with subcommands
for capturing CAN frames from a serial adapter and replaying previously
logged frames over a python-can interface.  It intentionally avoids any
heavy UI dependencies so it can run in a headless environment across
Windows, macOS and Linux.
"""

from __future__ import annotations

import argparse
import csv
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

# Optional imports – only required for certain commands.
try:
    import serial  # type: ignore
except Exception:  # pragma: no cover - serial might not be installed
    serial = None  # type: ignore

try:
    import can  # type: ignore
except Exception:  # pragma: no cover - python-can might not be installed
    can = None  # type: ignore

try:
    import cantools  # type: ignore
except Exception:  # pragma: no cover - cantools is optional
    cantools = None  # type: ignore

FRAME_RE = re.compile(
    r"ID:\s*0x([0-9A-Fa-f]+)\s*,\s*Data:\s*(?:DLC:\s*)?(\d+)\s+"
    r"([0-9A-Fa-f]{2}(?:\s+[0-9A-Fa-f]{2})*)"
)


@dataclass
class Frame:
    ts: float  # timestamp in seconds
    can_id: int
    dlc: int
    data: bytes


class CsvLogger:
    """Simple CSV logger with rotation."""

    def __init__(self, path: str) -> None:
        self.base_path = path
        self.path = path
        self.file = open(self.path, "a", newline="")
        self.writer = csv.writer(self.file)
        if self.file.tell() == 0:
            self.writer.writerow(["timestamp_ms", "id_hex", "dlc", "data_hex"])
            self.file.flush()

    def rotate(self) -> None:
        self.file.close()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{os.path.splitext(self.base_path)[0]}_{ts}.csv"
        os.rename(self.path, new_name)
        self.path = self.base_path
        self.file = open(self.path, "a", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["timestamp_ms", "id_hex", "dlc", "data_hex"])
        self.file.flush()

    def log(self, frame: Frame) -> None:
        self.writer.writerow([
            int(frame.ts * 1000),
            f"{frame.can_id:X}",
            frame.dlc,
            " ".join(f"{b:02X}" for b in frame.data),
        ])
        self.file.flush()
        if self.file.tell() > 100 * 1024 * 1024:
            self.rotate()

    def close(self) -> None:
        self.file.close()


class Stats:
    def __init__(self) -> None:
        self.data: Dict[int, Dict[str, float]] = {}

    def update(self, frame: Frame) -> None:
        info = self.data.setdefault(frame.can_id, {"count": 0, "last": frame.ts, "hz": 0.0})
        info["count"] += 1
        dt = frame.ts - info["last"]
        if dt > 0:
            hz = 1.0 / dt
            info["hz"] = info["hz"] * 0.8 + hz * 0.2 if info["hz"] else hz
        info["last"] = frame.ts

    def format(self) -> str:
        parts = []
        for can_id, info in sorted(self.data.items()):
            parts.append(f"0x{can_id:X}: {int(info['count'])} frames, {info['hz']:.1f} Hz")
        return " | ".join(parts) or "<no data>"


def parse_line(line: str) -> Optional[Tuple[int, int, bytes]]:
    match = FRAME_RE.search(line)
    if not match:
        return None
    can_id = int(match.group(1), 16)
    dlc = int(match.group(2))
    data_str = match.group(3).strip()
    try:
        data = bytes(int(x, 16) for x in data_str.split())
    except ValueError:
        return None
    return can_id, dlc, data


def format_frame(frame: Frame, dbc_db=None) -> str:
    ts = datetime.fromtimestamp(frame.ts).strftime("%H:%M:%S.%f")[:-3]
    base = f"{ts} | ID: 0x{frame.can_id:X} | DLC: {frame.dlc} | DATA: " + \
        " ".join(f"{b:02X}" for b in frame.data)
    if dbc_db:
        try:
            msg = dbc_db.get_message_by_frame_id(frame.can_id)
            decoded = dbc_db.decode_message(msg.frame_id, frame.data)
            decoded_str = " | " + \
                ", ".join(f"{k}={v}" for k, v in decoded.items())
            base += decoded_str
        except Exception:
            pass
    return base


def keyboard_listener(cmd_queue: "queue.Queue[str]", stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            ch = sys.stdin.read(1)
            if not ch:
                continue
            cmd_queue.put(ch.strip().lower())
        except Exception:
            break


def print_overlay(status: str, filters: Iterable[int], capture_path: Optional[str],
                   extra: str = "") -> None:
    filt = ",".join(f"0x{x:X}" for x in filters) if filters else "<none>"
    cap = f"ON ({capture_path})" if capture_path else "OFF"
    overlay = (
        f"STATUS: {status} | Filters: {filt} | Capture: {cap} | "
        "[P]ause [R]esume [F]ilter [C]apture toggle [I]nfo [Q]uit" + extra
    )
    sys.stdout.write("\r" + overlay + " " * max(0, 80 - len(overlay)))
    sys.stdout.flush()


def cmd_serial(args: argparse.Namespace) -> None:
    if serial is None:
        print("pyserial not installed", file=sys.stderr)
        return

    ser = serial.Serial(args.port, args.baud, timeout=0.1)
    cmd_q: "queue.Queue[str]" = queue.Queue()
    stop_event = threading.Event()
    t = threading.Thread(target=keyboard_listener, args=(cmd_q, stop_event), daemon=True)
    t.start()

    logger = CsvLogger(args.out) if args.out else None
    dbc_db = None
    if args.dbc and cantools:
        try:
            dbc_db = cantools.database.load_file(args.dbc)
        except Exception as exc:  # pragma: no cover - parsing errors are non-fatal
            print(f"DBC load failed: {exc}", file=sys.stderr)
            dbc_db = None

    filters: List[int] = []
    paused = False
    stats = Stats()

    try:
        print_overlay("RUNNING", filters, logger.path if logger else None)
        while not stop_event.is_set():
            try:
                line = ser.readline().decode(errors="ignore")
            except Exception:
                break
            if not line:
                pass
            else:
                if not paused:
                    parsed = parse_line(line)
                    if parsed:
                        can_id, dlc, data = parsed
                        if not filters or can_id in filters:
                            frame = Frame(time.time(), can_id, dlc, data)
                            stats.update(frame)
                            print("\r" + format_frame(frame, dbc_db))
                            if logger:
                                logger.log(frame)
                            print()
                            print_overlay("RUNNING", filters, logger.path if logger else None)
            # Handle commands
            while not cmd_q.empty():
                cmd = cmd_q.get()
                if cmd == "p":
                    paused = True
                    print_overlay("PAUSED", filters, logger.path if logger else None)
                elif cmd == "r":
                    paused = False
                    print_overlay("RUNNING", filters, logger.path if logger else None)
                elif cmd == "c":
                    if logger:
                        logger.close()
                        logger = None
                    else:
                        if args.out:
                            logger = CsvLogger(args.out)
                    print_overlay("RUNNING" if not paused else "PAUSED",
                                   filters, logger.path if logger else None)
                elif cmd == "f":
                    sys.stdout.write("\nEnter filter IDs (comma separated, empty to clear): ")
                    sys.stdout.flush()
                    line = sys.stdin.readline().strip()
                    if line:
                        filters = [int(x, 16) for x in line.split(",")]
                    else:
                        filters = []
                    print_overlay("RUNNING" if not paused else "PAUSED",
                                   filters, logger.path if logger else None)
                elif cmd == "i":
                    sys.stdout.write("\n" + stats.format() + "\n")
                    print_overlay("RUNNING" if not paused else "PAUSED",
                                   filters, logger.path if logger else None)
                elif cmd == "q":
                    stop_event.set()
        print("\nExiting...")
    finally:
        stop_event.set()
        t.join(timeout=1.0)
        ser.close()
        if logger:
            logger.close()


def load_csv_frames(path: str) -> List[Frame]:
    frames: List[Frame] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(row["timestamp_ms"]) / 1000.0
                can_id = int(row["id_hex"], 16)
                dlc = int(row["dlc"])
                data = bytes(int(x, 16) for x in row["data_hex"].split())
                frames.append(Frame(ts, can_id, dlc, data))
            except Exception:
                continue
    return frames


def cmd_replay(args: argparse.Namespace) -> None:
    if can is None:
        print("python-can not installed", file=sys.stderr)
        return
    frames = load_csv_frames(args.input)
    if not frames:
        print("No frames in file", file=sys.stderr)
        return
    try:
        bus = can.interface.Bus(bustype=args.channel or "socketcan", channel=args.channel,
                                bitrate=None)
    except Exception:
        bus = can.interface.Bus(bustype="virtual")

    cmd_q: "queue.Queue[str]" = queue.Queue()
    stop_event = threading.Event()
    t = threading.Thread(target=keyboard_listener, args=(cmd_q, stop_event), daemon=True)
    t.start()
    playing = True
    stats = Stats()
    print_overlay("REPLAYING", [], None, " [S]top")
    try:
        while not stop_event.is_set():
            last_ts = None
            for frame in frames:
                while not playing and not stop_event.is_set():
                    time.sleep(0.1)
                if stop_event.is_set():
                    break
                if last_ts is not None:
                    delay = (frame.ts - last_ts) / args.rate
                    if delay > 0:
                        time.sleep(delay)
                last_ts = frame.ts
                msg = can.Message(arbitration_id=frame.can_id, data=frame.data, is_extended_id=False)
                try:
                    bus.send(msg)
                except Exception:
                    pass
                stats.update(Frame(time.time(), frame.can_id, frame.dlc, frame.data))
                sys.stdout.write("\r" + format_frame(Frame(time.time(), frame.can_id, frame.dlc, frame.data)))
                print()
                print_overlay("REPLAYING" if playing else "STOPPED", [], None, " [S]top")
                while not cmd_q.empty():
                    cmd = cmd_q.get()
                    if cmd == "s":
                        playing = not playing
                        print_overlay("REPLAYING" if playing else "STOPPED", [], None, " [S]top")
                    elif cmd == "i":
                        sys.stdout.write("\n" + stats.format() + "\n")
                        print_overlay("REPLAYING" if playing else "STOPPED", [], None, " [S]top")
                    elif cmd == "q":
                        stop_event.set()
                        break
            if not args.loop:
                break
    finally:
        stop_event.set()
        t.join(timeout=1.0)
        bus.shutdown()
        print("\nExiting...")


def cmd_pid(args: argparse.Namespace) -> None:
    if can is None:
        print("python-can not installed", file=sys.stderr)
        return
    try:
        bus = can.interface.Bus(bustype=args.channel or "socketcan", channel=args.channel,
                                bitrate=None)
    except Exception:
        bus = can.interface.Bus(bustype="virtual")

    pids = {0x0C: "RPM", 0x0D: "SPEED", 0x11: "THROTTLE", 0x05: "COOLANT"}
    for pid, name in pids.items():
        msg = can.Message(arbitration_id=0x7DF,
                          data=bytes([0x02, 0x01, pid, 0, 0, 0, 0, 0]),
                          is_extended_id=False)
        try:
            bus.send(msg)
            resp = bus.recv(1.0)
            if resp and len(resp.data) >= 4:
                val = resp.data[3]
                if pid == 0x0C:
                    val = (resp.data[3] << 8 | resp.data[4]) / 4
                print(f"{name}: {val}")
            else:
                print(f"No response for PID {name}")
        except Exception:
            print(f"Error sending PID {name}")
    bus.shutdown()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="canrx", description="CAN reverse engineering helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("serial", help="Capture from serial")
    ps.add_argument("--port", required=True)
    ps.add_argument("--baud", type=int, required=True)
    ps.add_argument("--out", default="canlog.csv")
    ps.add_argument("--dbc", default=None)
    ps.set_defaults(func=cmd_serial)

    pr = sub.add_parser("replay", help="Replay from CSV")
    pr.add_argument("--in", dest="input", required=True)
    pr.add_argument("--channel", default="can0")
    pr.add_argument("--rate", type=float, default=1.0)
    pr.add_argument("--loop", action="store_true")
    pr.set_defaults(func=cmd_replay)

    pid = sub.add_parser("pid", help="Query basic OBD-II PIDs")
    pid.add_argument("--channel", default="can0")
    pid.set_defaults(func=cmd_pid)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


"""
README
======

Usage examples::

    # Capture frames from serial port
    python canrx.py serial --port COM9 --baud 115200 --out canlog.csv

    # Replay a captured log
    python canrx.py replay --in canlog.csv --channel can0 --rate 1.0

    # Query a few OBD-II PIDs (optional)
    python canrx.py pid --channel can0
"""
