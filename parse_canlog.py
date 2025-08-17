import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class CANFrame:
    timestamp_ms: int
    can_id: int
    dlc: int
    data: List[int]


def parse_canlog(path: str) -> List[CANFrame]:
    frames: List[CANFrame] = []
    with open(path, newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0] == 'timestamp_ms':
                continue
            ts = int(row[0])
            can_id = int(row[1], 16)
            dlc = int(row[2])
            data_bytes = [int(byte, 16) for byte in row[3].split()]
            frames.append(CANFrame(ts, can_id, dlc, data_bytes))
    return frames


def summarize_frames(frames: List[CANFrame]) -> None:
    print(f"Total frames: {len(frames)}")
    id_counts = Counter(f.can_id for f in frames)
    print("Top CAN IDs:")
    for can_id, count in id_counts.most_common(10):
        print(f"  0x{can_id:03X}: {count}")

    # show example payloads for each id
    payload_examples: Dict[int, set] = defaultdict(set)
    for f in frames:
        payload_examples[f.can_id].add(tuple(f.data))

    print("\nSample payloads:")
    for can_id, examples in payload_examples.items():
        ex_list = list(examples)[:3]
        ex_str = ', '.join(' '.join(f"{b:02X}" for b in ex) for ex in ex_list)
        print(f"  0x{can_id:03X}: {ex_str}")


def decode_obd_pid(frame: CANFrame):
    if not frame.data:
        return None
    if frame.data[0] == 0x41 and len(frame.data) >= 3:
        pid = frame.data[1]
        if pid == 0x0C and len(frame.data) >= 4:
            rpm = ((frame.data[2] * 256) + frame.data[3]) / 4
            return f"Engine RPM: {rpm}"
        elif pid == 0x0D and len(frame.data) >= 3:
            speed = frame.data[2]
            return f"Vehicle Speed: {speed} km/h"
        elif pid == 0x11 and len(frame.data) >= 3:
            throttle = frame.data[2] * 100 / 255
            return f"Throttle Position: {throttle:.1f}%"
        elif pid == 0x05 and len(frame.data) >= 3:
            temp = frame.data[2] - 40
            return f"Coolant Temp: {temp} °C"
        else:
            return f"PID 0x{pid:02X} data: {' '.join(f'{b:02X}' for b in frame.data[2:])}"
    return None


if __name__ == '__main__':
    frames = parse_canlog('CANLOG.CSV')
    summarize_frames(frames)
    print("\nOBD-II decodes:")
    for f in frames:
        decoded = decode_obd_pid(f)
        if decoded:
            print(f"  ts {f.timestamp_ms} id 0x{f.can_id:03X}: {decoded}")
