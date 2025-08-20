"""Neon drenched CAN bus utility.

This rewrite distils the earlier experiments into a focused tool that can:

* log frames arriving over a serial connection (typically from an Arduino)
* transmit commands defined in a DBC file
* interactively query common OBD‑II PIDs

Everything is wrapped in loud ANSI colour to keep the retro cyber‑punk
vibes alive.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional


# Optional third‑party modules -------------------------------------------------
try:  # pragma: no cover - optional dependency
    import serial  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    serial = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import cantools  # type: ignore
    import can  # python-can
except Exception:  # pragma: no cover - optional dependency
    cantools = None  # type: ignore
    can = None  # type: ignore


# A splash of neon -------------------------------------------------------------
NEON_MAGENTA = "\033[95m"
NEON_CYAN = "\033[96m"
NEON_GREEN = "\033[92m"
RESET = "\033[0m"

BANNER = f"""
{NEON_MAGENTA}
 ██████╗  █████╗ ███╗   ██╗██████╗  ██████╗ ████████╗
██╔════╝ ██╔══██╗████╗  ██║██╔══██╗██╔═══██╗╚══██╔══╝
██║  ███╗███████║██╔██╗ ██║██████╔╝██║   ██║   ██║   
██║   ██║██╔══██║██║╚██╗██║██╔══██╗██║   ██║   ██║   
╚██████╔╝██║  ██║██║ ╚████║██████╔╝╚██████╔╝   ██║   
 ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝  ╚═════╝    ╚═╝   
            CANB0T • REBOOTED IN LIVING COLOUR
{RESET}
"""


def neon(text: str, colour: str = NEON_CYAN) -> str:
    """Wrap ``text`` in ANSI colour codes."""

    return f"{colour}{text}{RESET}"


def log_line(message: str, colour: str = NEON_GREEN) -> None:
    """Emit a timestamped, colourised log line."""

    stamp = time.strftime("%H:%M:%S")
    print(neon(f"[LOG {stamp}] {message}", colour))


def system_alert(message: str) -> None:
    """Blare a warning message in glorious magenta."""

    print(neon(f"[SYSTEM] {message}", NEON_MAGENTA))


def print_divider() -> None:
    print(neon("═" * 60, NEON_MAGENTA))


# CAN frame & PID definitions --------------------------------------------------
@dataclass
class CANFrame:
    """Minimal representation of a CAN frame."""

    timestamp_ms: int
    can_id: int
    dlc: int
    data: list[int]


# pid -> (name, decode_fn)
PID_MAP: dict[int, tuple[str, callable[[list[int]], str]]] = {
    0x0C: (
        "ENGINE_RPM",
        lambda d: f"Engine RPM: {((d[0] << 8) + d[1]) / 4:.0f}",
    ),
    0x0D: ("VEHICLE_SPEED", lambda d: f"Vehicle Speed: {d[0]} km/h"),
    0x11: (
        "THROTTLE_POSITION",
        lambda d: f"Throttle Position: {d[0] * 100 / 255:.1f}%",
    ),
    0x05: ("COOLANT_TEMP", lambda d: f"Coolant Temp: {d[0] - 40} °C"),
}


class CANb0t:
    """All in one helper class."""

    def __init__(self) -> None:
        self.db = None  # type: ignore

    # -- Serial logging -------------------------------------------------
    def log_serial(self, port: str = "COM3", baudrate: int = 115200) -> None:
        """Listen to ``port`` and append frames to ``CANLOG.CSV``."""

        if serial is None:
            raise RuntimeError("pyserial not installed")

        import re
        import sys

        print_divider()
        log_line(f"Connecting to {port} @ {baudrate}", NEON_CYAN)
        log_line("Controls: [p]ause [r]esume [q]uit", NEON_MAGENTA)

        pattern = re.compile(r"ID: 0x([0-9A-F]+)\s+DLC:(\d+)\s+Data:(.*)")

        stop = False
        paused = False

        def control() -> None:
            nonlocal stop, paused
            for line in sys.stdin:
                cmd = line.strip().lower()
                if cmd == "p":
                    paused = True
                    log_line("Paused", NEON_MAGENTA)
                elif cmd == "r":
                    paused = False
                    log_line("Resumed", NEON_GREEN)
                elif cmd == "q":
                    stop = True
                    log_line("Stopping", NEON_MAGENTA)
                    break

        threading.Thread(target=control, daemon=True).start()

        with serial.Serial(port, baudrate, timeout=1) as ser, open("CANLOG.CSV", "a") as log:
            if log.tell() == 0:
                log.write("timestamp_ms,id,dlc,data\n")
            while not stop:
                if paused:
                    time.sleep(0.1)
                    continue
                line = ser.readline().decode("ascii", errors="ignore").strip()
                m = pattern.match(line)
                if not m:
                    continue
                ts_ms = int(time.time() * 1000)
                can_id = m.group(1)
                dlc = int(m.group(2))
                data = [int(b, 16) for b in m.group(3).strip().split() if b]
                log.write(
                    f"{ts_ms},{can_id},{dlc},{' '.join(f'{b:02X}' for b in data)}\n"
                )
                log.flush()

        log_line("Serial logging terminated", NEON_MAGENTA)

    # -- DBC loading / command sending ----------------------------------
    def load_dbc(self, path: str) -> None:
        if cantools is None:
            raise RuntimeError("cantools required to load DBC")
        self.db = cantools.database.load_file(path)

    def send_command(self, message: str, channel: str = "can0", **signals: float) -> bool:
        if self.db is None:
            raise RuntimeError("DBC not loaded")
        if can is None:
            raise RuntimeError("python-can required to send frames")
        msg = self.db.get_message_by_name(message)
        data = msg.encode(signals)
        iface = "socketcan" if hasattr(socket, "CMSG_SPACE") else "virtual"
        try:
            with can.interface.Bus(channel=channel, interface=iface) as bus:
                bus.send(can.Message(arbitration_id=msg.frame_id, data=data))
        except Exception as exc:  # pragma: no cover - hardware dependant
            system_alert(f"Send failed: {exc}")
            return False
        return True

    # -- PID handling ----------------------------------------------------
    def send_pid_request(
        self, pid: int, channel: str = "can0", timeout: float = 1.0
    ) -> Optional[str]:
        """Send a single PID request and decode the response."""

        if can is None:
            raise RuntimeError("python-can required for PID requests")
        data = bytes([0x02, 0x01, pid, 0, 0, 0, 0, 0])
        iface = "socketcan" if hasattr(socket, "CMSG_SPACE") else "virtual"
        try:
            with can.interface.Bus(channel=channel, interface=iface) as bus:
                bus.send(can.Message(arbitration_id=0x7DF, data=data))
                msg = bus.recv(timeout)
        except Exception as exc:  # pragma: no cover - hardware dependant
            system_alert(f"PID request failed: {exc}")
            return None
        if not msg:
            return None
        frame = CANFrame(int(time.time() * 1000), msg.arbitration_id, msg.dlc, list(msg.data))
        return self.decode_pid(frame)

    def decode_pid(self, frame: CANFrame) -> Optional[str]:
        if len(frame.data) < 4 or frame.data[1] != 0x41:
            return None
        pid = frame.data[2]
        payload = frame.data[3:]
        if pid in PID_MAP:
            name, decoder = PID_MAP[pid]
            return decoder(payload)
        return f"PID 0x{pid:02X}: {' '.join(f'{b:02X}' for b in payload)}"

    def pid_console(self, channel: str = "can0") -> None:
        """Interactive PID request loop."""

        while True:
            print_divider()
            print(neon("Select PID (0 to exit):", NEON_MAGENTA))
            for idx, (pid, (name, _)) in enumerate(PID_MAP.items(), start=1):
                print(neon(f"{idx}. {name} (0x{pid:02X})"))
            choice = input("[PID] > ")
            if choice == "0":
                break
            try:
                pid = list(PID_MAP.keys())[int(choice) - 1]
            except (ValueError, IndexError):
                system_alert("Invalid selection")
                continue
            resp = self.send_pid_request(pid, channel)
            if resp:
                log_line(resp)
            else:
                system_alert("No response")

    def _load_recent_values(self, log_path: str = "CANLOG.CSV") -> dict[str, dict[str, float]]:
        """Return last observed signal values for messages in ``log_path``.

        The CSV is expected to contain lines of ``timestamp_ms,id,dlc,data`` with
        hexadecimal identifiers and byte values separated by spaces.  Each line is
        decoded using the currently loaded DBC so that signal defaults can be
        prepopulated when sending commands interactively.
        """

        defaults: dict[str, dict[str, float]] = {}
        if self.db is None:
            return defaults
        try:
            with open(log_path) as log:
                next(log, None)  # skip header if present
                for line in log:
                    parts = line.strip().split(",", 3)
                    if len(parts) < 4:
                        continue
                    _, can_id, _, data_str = parts
                    try:
                        frame_id = int(can_id, 16)
                        msg = self.db.get_message_by_frame_id(frame_id)
                    except Exception:
                        continue
                    data = bytes(int(b, 16) for b in data_str.split())
                    try:
                        decoded = msg.decode(data)
                    except Exception:
                        continue
                    defaults[msg.name] = decoded
        except FileNotFoundError:
            pass
        return defaults

    # -- Interactive command sender ------------------------------------
    def interactive_send(self, channel: str = "can0") -> None:
        if self.db is None:
            system_alert("DBC not loaded")
            return
        messages = self.db.messages
        print_divider()
        for idx, msg in enumerate(messages, start=1):
            print(neon(f"{idx}. {msg.name}"))
        try:
            idx = int(input("Select message: "))
            chosen = messages[idx - 1]
        except (ValueError, IndexError):
            system_alert("Invalid selection")
            return
        defaults = self._load_recent_values()
        prior = defaults.get(chosen.name, {})
        values: dict[str, float] = {}
        for sig in chosen.signals:
            default_val = prior.get(sig.name, getattr(sig, "initial", 0))
            val = input(f"{sig.name} [{default_val}]: ")
            if val:
                try:
                    values[sig.name] = float(val)
                except ValueError:
                    system_alert(f"Invalid value for {sig.name}")
            else:
                values[sig.name] = float(default_val)
        if self.send_command(chosen.name, channel, **values):
            log_line("TRANSMISSION COMPLETE", NEON_GREEN)

    # -- Menu -----------------------------------------------------------
    def main_menu(self) -> None:
        while True:
            print_divider()
            print(neon("Select function:", NEON_MAGENTA))
            print(neon("1. Log frames from serial port"))
            print(neon("2. Send command from DBC"))
            print(neon("3. Interactive PID console"))
            print(neon("0. EXIT", NEON_MAGENTA))
            choice = input("[CMD] > ")
            if choice == "1":
                port = input("Serial port [COM3]: ") or "COM3"
                try:
                    baud = int(input("Baudrate [115200]: ") or "115200")
                except ValueError:
                    system_alert("Invalid baudrate")
                    continue
                self.log_serial(port, baud)
            elif choice == "2":
                dbc = input("DBC path: ")
                try:
                    self.load_dbc(dbc)
                except Exception as exc:
                    system_alert(str(exc))
                    continue
                channel = input("Channel [can0]: ") or "can0"
                self.interactive_send(channel)
            elif choice == "3":
                channel = input("Channel [can0]: ") or "can0"
                self.pid_console(channel)
            elif choice == "0":
                break
            else:
                system_alert("Invalid selection")


# CLI entry point --------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Neon soaked CAN bus utility")
    sub = parser.add_subparsers(dest="cmd")

    p_serial = sub.add_parser("serial", help="Log frames from a serial port")
    p_serial.add_argument("port", nargs="?", default="COM3")
    p_serial.add_argument("baudrate", type=int, nargs="?", default=115200)

    p_send = sub.add_parser("send", help="Send a command from a DBC")
    p_send.add_argument("dbc")
    p_send.add_argument("message", nargs="?")
    p_send.add_argument("signals", nargs="*", help="Signal=value pairs")
    p_send.add_argument("--channel", default="can0")

    p_pid = sub.add_parser("pid", help="Interactive PID console")
    p_pid.add_argument("--channel", default="can0")

    args = parser.parse_args()
    bot = CANb0t()
    print(BANNER)

    if args.cmd == "serial":
        bot.log_serial(args.port, args.baudrate)
    elif args.cmd == "send":
        bot.load_dbc(args.dbc)
        if args.message:
            values = {}
            for pair in args.signals:
                if "=" not in pair:
                    continue
                name, val = pair.split("=", 1)
                values[name] = float(val)
            if bot.send_command(args.message, args.channel, **values):
                log_line("TRANSMISSION COMPLETE", NEON_GREEN)
        else:
            bot.interactive_send(args.channel)
    elif args.cmd == "pid":
        bot.pid_console(args.channel)
    else:
        bot.main_menu()


if __name__ == "__main__":  # pragma: no cover - CLI behaviour
    main()

