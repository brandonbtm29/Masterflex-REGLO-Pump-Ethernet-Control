"""The REGLO's EtherNet/IP data layout: what the bytes in each assembly mean.

The pump is driven with raw CIP assembly messages (class 0x04, attribute 0x03):
instance 100 is the 56-byte input (status, read) and instance 112 the 28-byte output
(control, written about every 100 ms). The byte maps are also in the README.
No Qt or network code here, so it can be tested on its own.
"""

import struct
from dataclasses import dataclass

INPUT_INSTANCE = 100
OUTPUT_INSTANCE = 112
INPUT_SIZE = 56
OUTPUT_SIZE = 28

# Output byte 0: control bits
RUN = 0  # 1 = run, 0 = pause
RESET_DISPENSE = 1  # acts on a 1-to-0 transition
TOGGLE_REMOTE = 2  # acts on a 1-to-0 transition
CLEAR_VOLUME = 3  # acts on a 1-to-0 transition
DIRECTION_CCW = 6  # 1 = counter-clockwise

# Input bytes 0-3: status bits
_ST_OK, _ST_RUNNING, _ST_DISPENSING, _ST_HEAD_OPEN, _ST_REMOTE = 0, 1, 2, 4, 7

CONTINUOUS = 0  # dispense mode byte; the app always keeps the drive here (see dispense.py)

FLOW_UNITS = {
    0: "L/S",
    1: "mL/min",
    2: "mL/hr",
    3: "L/min",
    4: "L/hr",
    5: "L/day",
    6: "uL/min",
    7: "uL/hr",
    8: "gal/min",
    9: "gal/hr",
    10: "gal/day",
    11: "oz/min",
    12: "oz/hr",
    13: "cum/hr",
    14: "RPM",
    15: "%",
}

# Tube size code (input byte 5) -> inner diameter in mm. The manual's table for this is
# missing; this mapping was worked out during development and not every size is confirmed.
TUBE_CODES_MM = {
    1: 0.13,
    2: 0.19,
    3: 0.25,
    4: 0.38,
    5: 0.44,
    6: 0.51,
    7: 0.57,
    8: 0.64,
    9: 0.76,
    10: 0.89,
    11: 0.95,
    12: 1.02,
    13: 1.09,
    14: 1.14,
    15: 1.22,
    16: 1.33,
    17: 1.42,
    18: 1.52,
    19: 1.65,
    20: 1.75,
    21: 1.85,
    22: 2.06,
    23: 2.29,
    24: 2.54,
    25: 2.79,
    26: 3.17,
}


@dataclass(frozen=True)
class Status:
    ok: bool
    running: bool
    dispensing: bool
    head_open: bool
    remote: bool
    mode: int
    tube_code: int
    unit_code: int
    cum_volume: float
    batch: int
    min_flow: float
    flow: float
    max_flow: float

    @property
    def moving(self):
        """The pump reports that it is pumping (running or dispensing)."""
        return self.running or self.dispensing


def decode_status(data):
    """Unpack the 56-byte input assembly."""
    if len(data) < INPUT_SIZE:
        raise ValueError(f"expected {INPUT_SIZE} bytes, got {len(data)}")
    bits = struct.unpack_from("<i", data, 0)[0]
    return Status(
        ok=bool(bits >> _ST_OK & 1),
        running=bool(bits >> _ST_RUNNING & 1),
        dispensing=bool(bits >> _ST_DISPENSING & 1),
        head_open=bool(bits >> _ST_HEAD_OPEN & 1),
        remote=bool(bits >> _ST_REMOTE & 1),
        mode=data[4],
        tube_code=data[5],
        unit_code=data[6],
        cum_volume=struct.unpack_from("<f", data, 8)[0],
        batch=struct.unpack_from("<i", data, 24)[0],
        min_flow=struct.unpack_from("<f", data, 32)[0],
        flow=struct.unpack_from("<f", data, 36)[0],
        max_flow=struct.unpack_from("<f", data, 40)[0],
    )


def set_bit(out, bit, on):
    """Set or clear one control bit in output byte 0."""
    if on:
        out[0] |= 1 << bit
    else:
        out[0] &= ~(1 << bit) & 0xFF


def get_bit(out, bit):
    return bool(out[0] >> bit & 1)


def pack_parameters(out, *, flow, volume, on_time, off_time, batch):
    """Write the run parameters into the 28-byte output assembly.

    The drive is always left in continuous mode; Time and Volume programs run in software.
    """
    out[4] = CONTINUOUS
    struct.pack_into("<f", out, 8, flow)
    struct.pack_into("<f", out, 12, volume)
    struct.pack_into("<f", out, 16, on_time)
    struct.pack_into("<f", out, 20, off_time)
    struct.pack_into("<i", out, 24, batch)


def unit_code(name):
    """'mL/min' -> 1. Unknown names give 0 (L/S), as the app always has."""
    for code, unit in FLOW_UNITS.items():
        if unit == name:
            return code
    return 0


def unit_seconds(name):
    """Seconds in the time part of a flow unit ('mL/min' -> 60), or None for RPM and %."""
    if "/" not in name:
        return None
    per = name.split("/", 1)[1].lower()
    return {"s": 1, "sec": 1, "min": 60, "hr": 3600, "day": 86400}.get(per)


def volume_unit(name):
    """'mL/min' -> 'mL'; RPM and % are returned unchanged."""
    return name.split("/", 1)[0] if "/" in name else name


def estimate_rpm(flow, unit, max_flow, max_rpm):
    """Rough drive speed from the current flow.

    The pump doesn't report its speed, so this scales the flow by the pump's own maximum flow
    for the fitted tube (input bytes 40-43), which it reaches at ``max_rpm``.
    """
    if unit == "RPM":
        return flow
    if unit == "%":
        return flow / 100 * max_rpm
    return flow / max_flow * max_rpm if max_flow > 0 else 0.0
