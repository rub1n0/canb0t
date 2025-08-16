#!/usr/bin/env python3
"""CAN bus logger with retro hacker flair."""
import argparse
import csv
import os
import random
import socket
import sys
import time
from datetime import datetime
from contextlib import suppress
import logging

from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Load environment defaults
load_dotenv()

# Console setup: neon green on black
console = Console(style="bold green on black", highlight=False)

BANNER = r"""
   ███████╗ █████╗ ███╗   ██╗██████╗  ██████╗ ████████╗
  ██╔═══██╝██╔══██╗████╗  ██║██╔══██╗██╔═══██╗╚══██╔══╝
  ██║      ███████║██╔██╗ ██║██████╔╝██║   ██║   ██║   
  ██║   ██╗██╔══██║██║╚██╗██║██╔══██╗██║   ██║   ██║   
  ╚██████╔╝██║  ██║██║ ╚████║██████╔╝╚██████╔╝   ██║   
   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝  ╚═════╝    ╚═╝   
              CANBUS LOGGER • codename: canb0t
"""

ONE_LINERS = [
    "Feeding the grid with premium voltage...",
    "Ghosting through electromagnetic backdoors...",
    "ECU whisper decrypted — payload incoming...",
    "Hijacking packets with style and grace...",
    "Cipher matrix destabilized — channel wide open...",
]

INIT_COMMANDS = [
    ("ATZ", "Rebooting spy node"),
    ("ATE0", "Echo silencers engaged"),
    ("ATL0", "Trimming line feeds"),
    ("ATS0", "Stripping spaces"),
    ("ATH1", "Header injection enabled"),
    ("ATSP6", "Protocol set to ISO 15765-4 CAN")
]

PID_COMMANDS = {
    "RPM": "010C",
    "SPEED": "010D",
    "THROTTLE": "0111",
    "COOLANT": "0105",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retro CAN bus logger")
    parser.add_argument("--ip", default=os.getenv("IP", "192.168.0.10"), help="Adapter IP address")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 35000)), help="Adapter TCP port")
    parser.add_argument("--outfile", default=os.getenv("OUTFILE", "can_log.csv"), help="CSV output file")
    parser.add_argument("--logfile", default=os.getenv("LOGFILE", "canb0t.log"), help="debug log file")
    parser.add_argument(
        "--mode",
        choices=["sniff", "pid"],
        default=os.getenv("MODE", "sniff"),
        help="Operation mode: raw sniff or PID polling",
    )
    return parser.parse_args()


def send_command(sock: socket.socket, cmd: str, timeout: float = 1.0) -> str:
    """Send a command and return the response."""
    logging.debug("TX: %s", cmd)
    try:
        sock.sendall((cmd + "\r").encode())
        sock.settimeout(timeout)
        data = b""
        with suppress(socket.timeout):
            while not data.endswith(b">"):
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk
    except Exception:
        logging.exception("Communication error during '%s'", cmd)
        raise
    resp = data.decode(errors="ignore")
    logging.debug("RX: %s", resp.strip())
    return resp


def init_elm327(sock: socket.socket) -> None:
    for cmd, desc in INIT_COMMANDS:
        with console.status(f"{desc}…", spinner="dots"):
            resp = send_command(sock, cmd)
        console.print(f"{cmd}: [bold green]ACCESS GRANTED[/]")
        time.sleep(0.2)


def make_panel(frame_count: int, id_set: set, start: float) -> Panel:
    elapsed = time.monotonic() - start
    fps = frame_count / elapsed if elapsed else 0
    table = Table.grid(expand=True)
    table.add_row("Frames Captured", str(frame_count))
    table.add_row("Unique IDs", str(len(id_set)))
    table.add_row("Capture Rate", f"{fps:.1f} fps")
    return Panel(table, title="[cyan]DATA SIPHON", border_style="green")


def sniff_mode(sock: socket.socket, writer: csv.writer) -> int:
    console.print("ESTABLISHING LINK TO TARGET ECU…")
    send_command(sock, "ATMA")
    frame_count = 0
    id_set = set()
    start = time.monotonic()
    f = sock.makefile()
    with Live(make_panel(frame_count, id_set, start), console=console, refresh_per_second=4) as live:
        while True:
            line = f.readline()
            if not line:
                continue
            line = line.strip()
            if not line or line.startswith("OK"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            can_id, dlc = parts[0], parts[1]
            data = " ".join(parts[2:])
            ts_iso = datetime.utcnow().isoformat() + "Z"
            ts_ms = int((time.monotonic() - start) * 1000)
            writer.writerow([ts_iso, ts_ms, can_id, dlc, data])
            frame_count += 1
            if can_id not in id_set:
                id_set.add(can_id)
                console.print(f">>> SUBSYSTEM NODE {can_id} BREACHED <<<")
            if random.random() < 0.01:
                console.log(random.choice(ONE_LINERS))
            live.update(make_panel(frame_count, id_set, start))
    return frame_count


def pid_mode(sock: socket.socket, writer: csv.writer) -> int:
    console.print("INITIATING PID QUERY SEQUENCE…")
    frame_count = 0
    id_set = set()
    start = time.monotonic()
    f = sock.makefile()
    try:
        while True:
            for name, cmd in PID_COMMANDS.items():
                send_command(sock, cmd)
                line = f.readline().strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                can_id, dlc = parts[0], parts[1]
                data = " ".join(parts[2:])
                ts_iso = datetime.utcnow().isoformat() + "Z"
                ts_ms = int((time.monotonic() - start) * 1000)
                writer.writerow([ts_iso, ts_ms, can_id, dlc, data])
                frame_count += 1
                if can_id not in id_set:
                    id_set.add(can_id)
                    console.print(f">>> SUBSYSTEM NODE {can_id} BREACHED <<<")
                if random.random() < 0.05:
                    console.log(f"{name} data siphoned…")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return frame_count


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        filename=args.logfile,
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s: %(message)s",
        filemode="w",
    )
    logging.info("canb0t starting")
    console.print(Text(BANNER, style="bold green"))
    console.print("INTRUSION COUNTERMEASURES ENGAGED — [BYPASSED]")

    start_time = time.monotonic()
    frame_count = 0
    try:
        logging.info("Connecting to %s:%s", args.ip, args.port)
        with socket.create_connection((args.ip, args.port)) as sock, open(args.outfile, "w", newline="") as csvfile:
            logging.info("Connection established")
            writer = csv.writer(csvfile)
            writer.writerow(["timestamp_iso", "ts_ms", "id", "dlc", "data_hex"])
            init_elm327(sock)
            console.print("STREAM TAP OPENED — DATA SIPHON ACTIVE.")
            logging.info("Starting %s mode", args.mode)
            if args.mode == "sniff":
                frame_count = sniff_mode(sock, writer)
            else:
                frame_count = pid_mode(sock, writer)
    except KeyboardInterrupt:
        console.print("\nControl-C received — shutting down link…")
        logging.info("Interrupted by user")
    except Exception as exc:
        logging.exception("Link failure")
        console.print(f"[red]LINK FAILURE:[/] {exc}")
    finally:
        duration = time.monotonic() - start_time
        console.print("\n*** MISSION TERMINATED ***")
        console.print(f"Frames Captured: {frame_count}")
        console.print(f"Operation Time: {time.strftime('%H:%M:%S', time.gmtime(duration))}")
        console.print("SYSTEM BREACH SUCCESSFUL — DATA STORED")
        logging.info("Frames Captured: %s", frame_count)
        logging.info(
            "Operation Time: %s", time.strftime('%H:%M:%S', time.gmtime(duration))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
