# Masterflex REGLO Pump Controller GUI

This project is a custom Python GUI built with `customtkinter` and `pycomm3` to control a Masterflex REGLO Digital Pump Drive via EtherNet/IP.

## Technology Stack & Execution
- **Python Version**: 3.x
- **UI Framework**: `customtkinter`
- **Networking Protocol**: EtherNet/IP (Explicit Messaging Protocol)
- **Library**: `pycomm3`

Run the interface with: `python pump_gui.py`

## Critical Project Learnings

If you are expanding this software in the future, please carefully review these extremely important nuances about the Masterflex hardware that we discovered during development:

### 1. The `LogixDriver` Bypass Bug
You cannot connect to this equipment using a regular `pycomm3` initialization routine. Masterflex does not fully support the stringent identity verification handshakes utilized by Allen-Bradley/Rockwell PLCs. If the script attempts to pull the standard Identity Object or fetch Tag Lists, the pump will crash the connection.
**Solution implemented:** The `pump_gui.py` script declares a custom `PumpDriver` class that subclasses `pycomm3.LogixDriver` and explicitly overrides `_initialize_driver` with `pass`. This completely skips the tag database setup while keeping the powerful networking engines.

### 2. The 100ms I/O Watchdog
The pump has an incredibly aggressive internal safety "heartbeat" watchdog. If you are operating in **Remote Control Mode** and the pump does not receive an EtherNet/IP data packet for longer than a few hundred milliseconds, it will immediately pause its motor. 
**Solution implemented:** The GUI spins up a background Python threading daemon (`self.poll_data()`) that fires the entire 28-Byte Output array to the pump every 100 milliseconds perpetually while connected.

### 3. CIP Assembly Instances
The pump DOES NOT support standard String Tag writes (i.e. you cannot just write to `Output.Run`). You must perform RAW Explicit Messaging over Generic CIP Assemblies (Class Code `0x04`, Attribute `0x03`).
- **Target Instance 100 (Read)**: 56 Bytes long. This is the **Input Assembly**.
- **Target Instance 112 (Write)**: 28 Bytes long. This is the **Output Assembly**.

## Byte Matrix Maps

When making future UI additions, use these confirmed byte mappings to unpack/pack the data strings.

### Input Data Array (Read Instance 100 - 56 Bytes)
| Byte Offset | Data Type | Function |
|-------------|-----------|----------|
| 0-3 | 32-bit INT | **Pump Status**. Bit 0: Status OK, Bit 1: Pump Running, Bit 2: Dispense Running, Bit 4: Head Open, Bit 7: Remote Mode Active |
| 4 | BYTE | Dispense Mode (0=Continuous, 1=Time, 2=Volume) |
| 5 | BYTE | Tube Size Index Code (NOTE: Table 4 translation is missing from the Masterflex manual!) |
| 6 | BYTE | Flow Units Index Code (Maps to Table 3) |
| 8-11 | FLOAT | Cumulative Volume |
| 24-27 | 32-bit INT| Batch Count Current |
| 32-35 | FLOAT | Minimum Flow Rate Limit |
| 36-39 | FLOAT | Current Real-Time Flow Rate |
| 40-43 | FLOAT | Maximum Flow Rate Limit |

### Output Data Array (Write Instance 112 - 28 Bytes)
| Byte Offset | Data Type | Function |
|-------------|-----------|----------|
| 0 | BYTE | **Pump Control**. Bit 0: Set Run/Pause (1=Run, 0=Pause), Bit 1: Stop/Reset Dispense (1-to-0 transition clear pulse pattern), Bit 2: Toggle Remote Mode (1-to-0 transition pattern), Bit 3: Clear Cumulative Vol (1-to-0 transition pattern), Bit 6: Set Flow Direction (1=CCW, 0=CW) |
| 4 | BYTE | Set Dispense Mode (0=Continuous, 1=Time, 2=Volume) |
| 6 | BYTE | Set Flow Units Master Index (0-15 mapped against Table 3) |
| 8-11 | FLOAT | Set Flow Rate |
| 12-15 | FLOAT | Set Dispense Volume |
| 16-19 | FLOAT | Set Dispense On / Run Seconds |
| 20-23 | FLOAT | Set Dispense Off / Interval Pause Seconds |
| 24-27 | 32-bit INT| Set Batch Count Total (0 = infinite loops) |

## Units Mapping (Table 3)
When configuring Byte 6 for units, deploy this index:
`0: L/S, 1: mL/min, 2: mL/hr, 3: L/min, 4: L/hr, 5: L/day, 6: uL/min, 7: uL/hr, 8: gal/min, 9: gal/hr, 10: gal/day, 11: oz/min, 12: oz/hr, 13: cum/hr, 14: RPM, 15: %`
