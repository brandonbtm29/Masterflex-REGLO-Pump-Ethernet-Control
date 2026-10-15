"""protocol.py: the byte maps of the pump's input and output assemblies."""

import struct

import pytest
from conftest import fake_input

import protocol as p


def test_decode_status():
    st = p.decode_status(fake_input(status=0b10010111, tube=18, unit=1, cum_vol=2.5, batch=3, flow=5.0))
    assert (st.ok, st.running, st.dispensing, st.head_open, st.remote) == (True, True, True, True, True)
    assert st.moving
    assert (st.tube_code, st.unit_code, st.batch) == (18, 1, 3)
    assert st.cum_volume == 2.5 and st.flow == 5.0
    assert st.min_flow == pytest.approx(0.02) and st.max_flow == pytest.approx(14.69)


def test_decode_rejects_short_data():
    with pytest.raises(ValueError, match="56"):
        p.decode_status(bytes(10))


def test_bits_and_parameters():
    out = bytearray(p.OUTPUT_SIZE)
    p.set_bit(out, p.RUN, True)
    p.set_bit(out, p.DIRECTION_CCW, True)
    assert out[0] == 0b01000001 and p.get_bit(out, p.RUN)
    p.set_bit(out, p.RUN, False)
    assert out[0] == 0b01000000
    out[4] = 2
    p.pack_parameters(out, flow=2.5, volume=40, on_time=10, off_time=5, batch=3)
    assert out[4] == p.CONTINUOUS
    assert struct.unpack_from("<ffffi", out, 8) == (2.5, 40.0, 10.0, 5.0, 3)


@pytest.mark.parametrize(
    "unit, code, seconds, vol",
    [("mL/min", 1, 60, "mL"), ("L/S", 0, 1, "L"), ("gal/day", 10, 86400, "gal"), ("RPM", 14, None, "RPM")],
)
def test_units(unit, code, seconds, vol):
    assert p.unit_code(unit) == code
    assert p.unit_seconds(unit) == seconds
    assert p.volume_unit(unit) == vol


def test_estimate_rpm():
    assert p.estimate_rpm(5.0, "mL/min", 10.0, 160) == 80
    assert p.estimate_rpm(42, "RPM", 10.0, 160) == 42
    assert p.estimate_rpm(50, "%", 10.0, 160) == 80
    assert p.estimate_rpm(5.0, "mL/min", 0, 160) == 0
