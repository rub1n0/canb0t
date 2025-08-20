#!/usr/bin/env python3
"""CAN-bus reverse engineering helper.

This single-file script provides a menu-driven text UI for capturing CAN
frames from a serial port, replaying frames from CSV, and managing basic
settings.  It avoids heavy UI dependencies and relies only on the standard
library plus optional modules (pyserial, python-can, cantools).
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set

# Optional third‑party modules -------------------------------------------------
try:  # pyserial for serial capture
    import serial  # type: ignore
except Exception:  # pragma: no cover - optional
    serial = None

try:  # python-can for replay / PID demo
    import can  # type: ignore
except Exception:  # pragma: no cover - optional
    can = None

try:  # cantools for DBC decoding
    import cantools  # type: ignore
except Exception:  # pragma: no cover - optional
    cantools = None


# ----------------------------------------------------------------------------
# Configuration handling

PROFILE_FILE = ".canrx_profile.json"


@dataclass
class Config:
    """Runtime configuration and defaults."""

    port: str = "COM1"
    baud: int = 115200
    output_csv: str = "canlog.csv"
    dbc_path: str = ""
    input_csv: str = "canlog.csv"
    channel: str = "can0"
    rate: float = 1.0
    loop: bool = False

    # ------------------------------------------------------------------
    @classmethod
    def load(cls) -> "Config":
        try:
            with open(PROFILE_FILE, "r", encoding="utf8") as fh:
                data = json.load(fh)
            return cls(**data)
        except Exception:
            return cls()

    # ------------------------------------------------------------------
    def save(self) -> None:
        with open(PROFILE_FILE, "w", encoding="utf8") as fh:
            json.dump(asdict(self), fh, indent=2)


# ----------------------------------------------------------------------------
# Utility helpers

SERIAL_RE = re.compile(
    r"ID:\s*0x([0-9A-Fa-f]+)\s*,\s*(?:DLC|Data):\s*(\d+)\s+"
    r"([0-9A-Fa-f]{2}(?:\s+[0-9A-Fa-f]{2})*)"
)


def parse_serial_line(line: str) -> Optional[Dict]:
    """Parse a line from the serial adapter.

    Expected format: ``ID: 0x631, Data: 8 40 05 30 FF 00 40 00 00``
    Returns ``None`` for malformed lines.
    """

    m = SERIAL_RE.search(line)
    if not m:
        return None
    cid = int(m.group(1), 16)
    dlc = int(m.group(2))
    data_str = m.group(3).strip().split()
    data = [int(x, 16) for x in data_str]
    if len(data) != dlc:
        return None
    return {"id": cid, "dlc": dlc, "data": data}


def rotate_path(path: str) -> str:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(path)
    return f"{base}_{ts}{ext}"


# Keyboard polling ------------------------------------------------------------


class KeyboardPoller:
    """Cross-platform single character polling."""

    def __enter__(self) -> "KeyboardPoller":  # pragma: no cover - interactive
        if os.name != "nt":
            import termios, tty

            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc) -> None:  # pragma: no cover - interactive
        if os.name != "nt":
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def getch(self) -> Optional[str]:
        if os.name == "nt":  # pragma: no cover - windows
            import msvcrt

            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == "\r":
                    ch = "\n"
                return ch
            return None
        else:  # POSIX
            import select

            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
            return None


# CSV logging -----------------------------------------------------------------


class CSVLogger:
    """Append CAN frames to CSV with size-based rotation."""

    def __init__(self, path: str, enabled: bool = True) -> None:
        self.base_path = path
        self.enabled = enabled
        self.file = None
        if enabled:
            self._open()

    def _open(self) -> None:
        path = self.base_path
        new = not os.path.exists(path)
        self.file = open(path, "a", encoding="utf8", newline="")
        if new:
            self.file.write("timestamp_ms,id_hex,dlc,data_hex\n")
            self.file.flush()

    def toggle(self) -> None:
        self.enabled = not self.enabled
        if self.enabled and not self.file:
            self._open()

    def write(self, frame: Dict) -> None:
        if not self.enabled or not self.file:
            return
        if self.file.tell() > 100 * 1024 * 1024:  # rotate at ~100MB
            self.file.close()
            os.rename(self.base_path, rotate_path(self.base_path))
            self._open()
        ts_ms = int(frame["ts"] * 1000)
        data_hex = " ".join(f"{b:02X}" for b in frame["data"])
        self.file.write(f"{ts_ms},{frame['id']:X},{frame['dlc']},{data_hex}\n")
        self.file.flush()

    def close(self) -> None:
        if self.file:
            self.file.close()


# Statistics ------------------------------------------------------------------


class IDStats:
    def __init__(self) -> None:
        self.count = 0
        self.last_ts: Optional[float] = None
        self.hz = 0.0

    def update(self, ts: float) -> None:
        if self.last_ts is not None:
            delta = ts - self.last_ts
            if delta > 0:
                inst = 1.0 / delta
                self.hz = self.hz * 0.9 + inst * 0.1
        self.last_ts = ts
        self.count += 1


# Serial Capture ---------------------------------------------------------------


class SerialCapture(threading.Thread):
    """Background thread reading CAN frames from a serial port."""

    def __init__(
        self,
        port: str,
        baud: int,
        filters: Set[int],
        frame_q: queue.Queue,
        stats: Dict[int, IDStats],
        stop_event: threading.Event,
        pause_event: threading.Event,
        logger: CSVLogger,
        dbc: Optional[object] = None,
    ) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.filters = filters
        self.frame_q = frame_q
        self.stats = stats
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.logger = logger
        self.dbc = dbc

    def run(self) -> None:  # pragma: no cover - interactive
        if serial is None:
            print("pyserial not installed")
            return
        try:
            with serial.Serial(self.port, self.baud, timeout=0.1) as ser:
                while not self.stop_event.is_set():
                    if self.pause_event.is_set():
                        time.sleep(0.1)
                        continue
                    try:
                        line = ser.readline().decode(errors="ignore")
                    except Exception:
                        continue
                    frame = parse_serial_line(line)
                    if not frame:
                        continue
                    if self.filters and frame["id"] not in self.filters:
                        continue
                    frame["ts"] = time.time()
                    self.stats.setdefault(frame["id"], IDStats()).update(frame["ts"])
                    self.logger.write(frame)
                    if self.dbc:
                        frame["decoded"] = decode_frame(self.dbc, frame)
                    self.frame_q.put(frame)
        finally:
            self.logger.close()


def decode_frame(db: object, frame: Dict) -> str:
    try:
        msg = db.get_message_by_frame_id(frame["id"])
        data = bytes(frame["data"])
        signals = db.decode_message(msg.frame_id, data)
        return " " + " ".join(f"{k}={v}" for k, v in signals.items())
    except Exception:
        return ""


# Replay ----------------------------------------------------------------------


class ReplayThread(threading.Thread):
    def __init__(
        self,
        csv_path: str,
        channel: str,
        rate: float,
        loop: bool,
        frame_q: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self.csv_path = csv_path
        self.channel = channel
        self.rate = max(rate, 0.0001)
        self.loop = loop
        self.frame_q = frame_q
        self.stop_event = stop_event

    def _open_bus(self):  # pragma: no cover - interactive
        if can is None:
            return None
        try:
            return can.interface.Bus(self.channel, bustype="socketcan")
        except Exception:
            try:
                return can.interface.Bus(bustype="virtual")
            except Exception:
                return None

    def run(self) -> None:  # pragma: no cover - interactive
        bus = self._open_bus()
        while not self.stop_event.is_set():
            try:
                with open(self.csv_path, "r", encoding="utf8") as fh:
                    reader = csv.DictReader(fh)
                    prev_ts = None
                    for row in reader:
                        if self.stop_event.is_set():
                            break
                        try:
                            ts = int(row["timestamp_ms"]) / 1000.0
                            cid = int(row["id_hex"], 16)
                            dlc = int(row["dlc"])
                            data = [int(x, 16) for x in row["data_hex"].split()]
                        except Exception:
                            continue
                        if prev_ts is not None:
                            delay = (ts - prev_ts) / self.rate
                            time.sleep(max(0, delay))
                        prev_ts = ts
                        frame = {"id": cid, "dlc": dlc, "data": data, "ts": time.time()}
                        if bus is not None:
                            try:
                                msg = can.Message(arbitration_id=cid, data=bytes(data), dlc=dlc, is_extended_id=cid > 0x7FF)
                                bus.send(msg)
                            except Exception:
                                pass
                        self.frame_q.put(frame)
            except FileNotFoundError:
                break
            if not self.loop:
                break


# Menu helpers ----------------------------------------------------------------


def menu_prompt(title: str, options: List[str]) -> str:
    print(title)
    for line in options:
        print(line)
    return input("Select: ").strip()


# Capture Menu ----------------------------------------------------------------


def capture_menu(cfg: Config) -> None:
    filters: Set[int] = set()
    while True:
        print(
            "\nCapture — Serial\n"
            f"Port: {cfg.port}\tBaud: {cfg.baud}\n"
            f"DBC: {cfg.dbc_path or '(none)'}\tOutput: {cfg.output_csv}\n"
            f"Filters: {', '.join(hex(f) for f in filters) or '(none)'}\tCapture: ON\n"
            "Status: STOPPED\n\n"
            "A) Start Capture\n"
            "P) Pause / Resume\n"
            "F) Set Filters\n"
            "C) Toggle CSV Capture\n"
            "D) Load DBC file\n"
            "O) Change Output File\n"
            "B) Back to Main Menu\nQ) Quit"
        )
        choice = input("> ").strip().lower()
        if choice == "a":
            run_capture(cfg, filters)
        elif choice == "p":
            print("Nothing to pause/resume; start capture first.")
        elif choice == "f":
            val = input("Enter comma-separated hex IDs: ").strip()
            filters = {
                int(x, 16)
                for x in [s.strip() for s in val.split(",") if s.strip()]
            }
        elif choice == "c":
            cfg.output_csv = input("Output CSV: ") or cfg.output_csv
        elif choice == "d":
            cfg.dbc_path = input("DBC path: ") or cfg.dbc_path
        elif choice == "o":
            cfg.output_csv = input("Output CSV: ") or cfg.output_csv
        elif choice == "b":
            return
        elif choice == "q":
            sys.exit(0)


def run_capture(cfg: Config, filters: Set[int]) -> None:  # pragma: no cover - interactive
    frame_q: "queue.Queue[Dict]" = queue.Queue()
    stats: Dict[int, IDStats] = {}
    stop = threading.Event()
    pause = threading.Event()
    logger = CSVLogger(cfg.output_csv, enabled=True)
    dbc = None
    if cfg.dbc_path and cantools:
        try:
            dbc = cantools.database.load_file(cfg.dbc_path)
        except Exception:
            print("Failed to load DBC")

    cap = SerialCapture(cfg.port, cfg.baud, filters, frame_q, stats, stop, pause, logger, dbc)
    cap.start()
    status = "RUNNING"
    show_stats = False
    with KeyboardPoller() as kb:
        try:
            while not stop.is_set():
                try:
                    frame = frame_q.get(timeout=0.1)
                    line = (
                        time.strftime("%H:%M:%S", time.localtime(frame["ts"]))
                        + f".{int(frame['ts']%1*1000):03d} | ID: 0x{frame['id']:03X} | "
                        + f"DLC: {frame['dlc']} | DATA: "
                        + " ".join(f"{b:02X}" for b in frame["data"])
                    )
                    line += frame.get("decoded", "")
                    print(line)
                except queue.Empty:
                    pass

                if show_stats:
                    stat_line = " | ".join(
                        f"0x{i:03X}: {s.count} frames, {s.hz:.1f} Hz"
                        for i, s in stats.items()
                    )
                    if stat_line:
                        print(stat_line)
                    show_stats = False

                overlay = (
                    f"STATUS: {status} | Filters: "
                    + (",".join(hex(f) for f in filters) or "None")
                    + f" | Capture: {'ON' if logger.enabled else 'OFF'} ({cfg.output_csv})"
                    + " | Keys: [P]ause [R]esume [F]ilter [C]apture [I]nfo [Q]uit"
                )
                print(overlay, end="\r", flush=True)
                ch = kb.getch()
                if not ch:
                    continue
                ch = ch.lower()
                if ch == "p":
                    pause.set()
                    status = "PAUSED"
                elif ch == "r":
                    pause.clear()
                    status = "RUNNING"
                elif ch == "f":
                    val = input("\nFilter IDs: ")
                    filters.clear()
                    filters.update(
                        int(x, 16) for x in val.split(",") if x.strip()
                    )
                elif ch == "c":
                    logger.toggle()
                elif ch == "i":
                    show_stats = True
                elif ch == "q":
                    stop.set()
        finally:
            stop.set()
            cap.join()
            print("\nCapture stopped")


# Replay Menu -----------------------------------------------------------------


def replay_menu(cfg: Config) -> None:
    while True:
        print(
            "\nReplay — From CSV\n"
            f"Input: {cfg.input_csv}\n"
            f"Channel: {cfg.channel}\n"
            f"Rate: {cfg.rate}x\n"
            f"Loop: {'ON' if cfg.loop else 'OFF'}\n"
            "Status: STOPPED\n\n"
            "A) Start Replay\n"
            "S) Stop / Start Toggle\n"
            "R) Set Rate\n"
            "L) Toggle Loop\n"
            "I) Change Input CSV\n"
            "H) Change Channel\n"
            "B) Back to Main Menu\nQ) Quit"
        )
        choice = input("> ").strip().lower()
        if choice == "a":
            run_replay(cfg)
        elif choice == "r":
            try:
                cfg.rate = float(input("Rate: "))
            except ValueError:
                pass
        elif choice == "l":
            cfg.loop = not cfg.loop
        elif choice == "i":
            cfg.input_csv = input("Input CSV: ") or cfg.input_csv
        elif choice == "h":
            cfg.channel = input("Channel: ") or cfg.channel
        elif choice == "b":
            return
        elif choice == "q":
            sys.exit(0)


def run_replay(cfg: Config) -> None:  # pragma: no cover - interactive
    frame_q: "queue.Queue[Dict]" = queue.Queue()
    stop = threading.Event()
    rep = ReplayThread(cfg.input_csv, cfg.channel, cfg.rate, cfg.loop, frame_q, stop)
    rep.start()
    status = "REPLAYING"
    with KeyboardPoller() as kb:
        try:
            while not stop.is_set():
                try:
                    frame = frame_q.get(timeout=0.1)
                    line = (
                        time.strftime("%H:%M:%S", time.localtime(frame["ts"]))
                        + f".{int(frame['ts']%1*1000):03d} | ID: 0x{frame['id']:03X} | "
                        + f"DLC: {frame['dlc']} | DATA: "
                        + " ".join(f"{b:02X}" for b in frame["data"])
                    )
                    print(line)
                except queue.Empty:
                    pass
                overlay = (
                    f"STATUS: {status} | Keys: [S]top [Q]uit"
                )
                print(overlay, end="\r", flush=True)
                ch = kb.getch()
                if not ch:
                    continue
                ch = ch.lower()
                if ch == "s":
                    stop.set()
                elif ch == "q":
                    stop.set()
        finally:
            stop.set()
            rep.join()
            print("\nReplay stopped")


# PID Console (optional demo) -------------------------------------------------


def pid_console(cfg: Config) -> None:
    print("Simple PID console demo. Press Enter to request demo PIDs, Q to quit.")
    if can is None:
        print("python-can not available")
        return
    input("Press Enter to send requests...")
    try:
        bus = can.interface.Bus(channel=cfg.channel, interface="socketcan")
    except Exception:
        try:
            bus = can.interface.Bus(interface="virtual")
        except Exception:
            print("Unable to open CAN bus")
            return

    pids = [0x0C, 0x0D, 0x11, 0x05]
    try:
        for pid in pids:
            msg = can.Message(
                arbitration_id=0x7DF, data=[0x02, 0x01, pid, 0, 0, 0, 0, 0]
            )
            try:
                bus.send(msg)
                print(f"Requested PID 0x{pid:02X}")
            except Exception:
                pass
    finally:
        bus.shutdown()
    print("Done. Returning to menu.")


# Settings Menu ---------------------------------------------------------------


def settings_menu(cfg: Config) -> None:
    while True:
        print(
            "\nSettings\n"
            "1) Serial Port\n"
            "2) Serial Baud\n"
            "3) Default Output CSV\n"
            "4) Default DBC Path\n"
            "5) Save Profile\n"
            "6) Load Profile\n"
            "B) Back\n"
        )
        choice = input("> ").strip().lower()
        if choice == "1":
            cfg.port = input("Serial Port: ") or cfg.port
        elif choice == "2":
            try:
                cfg.baud = int(input("Baud: "))
            except ValueError:
                pass
        elif choice == "3":
            cfg.output_csv = input("Output CSV: ") or cfg.output_csv
        elif choice == "4":
            cfg.dbc_path = input("DBC Path: ") or cfg.dbc_path
        elif choice == "5":
            cfg.save()
            print("Profile saved")
        elif choice == "6":
            cfg.__dict__.update(asdict(Config.load()))
            print("Profile loaded")
        elif choice == "b":
            return


# About ----------------------------------------------------------------------


HELP_TEXT = """CAN RX Tool Help
Hotkeys vary per mode. CSV schema: timestamp_ms,id_hex,dlc,data_hex
Capture hotkeys: P=Pause R=Resume F=Filter C=Capture toggle I=Stats Q=Quit
Replay hotkeys: S=Stop Q=Quit
"""


def about_menu() -> None:
    print(HELP_TEXT)
    input("Press Enter to return...")


# Main Menu ------------------------------------------------------------------


def main_menu(cfg: Config) -> None:
    while True:
        choice = menu_prompt(
            "CAN RX Tool — Main Menu",
            [
                "1) Capture from Serial",
                "2) Replay from CSV",
                "3) Live PID Console (optional)",
                "4) Settings",
                "5) About / Help",
                "Q) Quit",
            ],
        ).lower()
        if choice == "1":
            capture_menu(cfg)
        elif choice == "2":
            replay_menu(cfg)
        elif choice == "3":
            pid_console(cfg)
        elif choice == "4":
            settings_menu(cfg)
        elif choice == "5":
            about_menu()
        elif choice == "q":
            break


# ----------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="CAN-bus reverse engineering tool")
    parser.add_argument("--capture", action="store_true", help="Start capture immediately")
    parser.add_argument("--replay", action="store_true", help="Start replay immediately")
    args = parser.parse_args(argv)

    cfg = Config.load()

    if args.capture:
        capture_menu(cfg)
    elif args.replay:
        replay_menu(cfg)
    else:
        main_menu(cfg)


if __name__ == "__main__":  # pragma: no cover
    main()


"""
README
======

Usage
-----

Run ``python canrx_tool.py`` with no arguments to launch the text-based menu.
From the Main Menu you can capture CAN frames from a serial adapter or replay
frames from a CSV log.  The tool prints each frame on its own line and maintains
an overlay status line with hotkeys.  Settings may be saved to a JSON profile
(``.canrx_profile.json``) for later reuse.

External libraries
------------------

* ``pyserial`` – required for serial capture.
* ``python-can`` – required for replay/PID console.
* ``cantools`` – optional DBC decoding.

The program gracefully degrades if these modules are absent.
"""

