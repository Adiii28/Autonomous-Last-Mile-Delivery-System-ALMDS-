# Hardware Reference

Complete hardware specification, wiring details, and calibration procedures for the ALMDS drone and drop-box.

---

## Component Overview

### Raspberry Pi 4 — Mission Computer

The Pi 4 (4GB RAM) is the central onboard computer. It runs all mission software: QR scanning, DroneKit flight commands, servo PWM, GSM AT commands, and the Flask API. It does not run flight control firmware — that lives on the dedicated flight controller.

- OS: Raspberry Pi OS Lite (64-bit, headless)
- Python: 3.11+
- Serial: `/dev/ttyAMA0` → Flight controller (MAVLink)
- Serial: `/dev/ttyUSB2` → SIM7600G-H (AT commands)
- I2C: Bus 1 → VL53L8CH ToF sensor
- GPIO: BCM 18 → Servo 1 (cargo door), BCM 23 → Servo 2 (payload drop)
- CSI-0: Camera 1 (docking station QR)
- CSI-1: Camera 2 (in-flight drop-box QR)

### Flight Controller — ArduCopter

Pixhawk or Cube Orange running ArduCopter firmware. Handles all real-time flight: motor mixing, PID loops, GPS navigation, EKF3 sensor fusion.

Communicates with the Pi over UART (MAVLink 2, 921600 baud). The Pi is treated as a Ground Control Station (`SYSID_MYGCS = 255`).

### ArduCam 8MP × 2 — Cameras

Both cameras are 8MP ArduCam modules connected via dedicated CSI-2 ribbon cables (not USB). CSI gives full bandwidth to the Pi's camera ports — no USB latency, no bandwidth sharing.

| Camera | Port | Use Case | Capture Profile |
|---|---|---|---|
| Camera 1 | CSI-0 | Docking station QR scan | 1920×1080, 30fps, fixed focus |
| Camera 2 | CSI-1 | In-flight drop-box identification | 1280×720, 30fps, auto-exposure |

Camera 2 uses a wider exposure range to handle variable outdoor lighting during approach.

### MG995 Servo × 2 — Actuation

Standard RC servo, metal gear, 10 kg·cm torque. Driven by the Pi's GPIO via `pigpio` daemon for precise PWM timing.

| Parameter | Value |
|---|---|
| Signal frequency | 50 Hz |
| Pulse width (closed) | 1.0 ms (1000 µs) |
| Pulse width (open) | 2.0 ms (2000 µs) |
| Operating voltage | 4.8–7.2V |
| Torque | 10 kg·cm @ 6V |

**Servo 1** (cargo door): mounted at the docking station bay. Opens to allow package loading, closes before arming.

**Servo 2** (payload drop): mounted on the drone frame. Holds the payload container string in closed position; releases on `DO_SET_SERVO` command.

### SIM7600G-H — 4G / GSM Module

Quad-band LTE Cat-4 module. Connects to the Pi over UART/USB. Controlled entirely via AT commands from the Pi's `comms/` module.

| Function | AT Command | Notes |
|---|---|---|
| Send SMS | `AT+CMGS="[number]"` | Delivery confirmation |
| Voice call | `AT+ATD[number];` | Customer notification |
| TCP connect | `AT+CIPSTART="TCP","host",port` | Dashboard telemetry stream |
| TCP send | `AT+CIPSEND=length` | Push telemetry data |
| Signal quality | `AT+CSQ` | Check before flight |

The module requires a physical SIM card with data + voice + SMS capabilities.

### ESP32-S3 — Wi-Fi Bridge (Onboard)

Wi-Fi 6 (802.11ax) microcontroller with dual external IPEX/U.FL antennas. Acts as the local wireless bridge between the Pi and the operator's laptop at the docking station.

The dual external antennas are critical — the metal drone frame creates RF dead zones that would severely limit a PCB antenna's range. External antennas extend effective range and maintain stable connection during pre-flight operations.

### ESP32-S3 — Drop-box Controller (Remote)

A second ESP32-S3 at the delivery address controls the drop-box mechanism. It communicates with the Pi over 4G (via the dashboard backend) to:

1. Open the drop-box lid on payload release signal
2. Confirm package receipt via a weight sensor or IR break-beam
3. Close the lid after confirmation
4. Push delivery confirmation to the dashboard

### VL53L8CH — Time-of-Flight Sensor

ST Microelectronics multi-zone ToF sensor. Provides an **8×8 grid of independent ranging zones** (64 measurements per frame) via I2C.

This is fundamentally different from a single-point altimeter:

| Single-point altimeter | VL53L8CH 8×8 grid |
|---|---|
| One distance reading | 64 distance readings |
| Can't detect surface tilt | Detects slope and uneven surfaces |
| No spatial awareness | Maps the surface below the drone |
| Hard drop risk on uneven ground | Adjusts hover before release |

Used during the final descent: the Pi reads the 8×8 grid, checks that the surface variance is within tolerance, and only releases the payload when the drone is at the correct height above the drop-box.

| Parameter | Value |
|---|---|
| Interface | I2C (address 0x29) |
| Ranging zones | 8×8 (64 zones) |
| Max range | 4m (typical) |
| Timing budget | 50ms per frame |
| FoV | 65° diagonal |

### Power System

Dual Li-Ion battery pack (2× cells, 5V 3A regulated output). Dual-battery redundancy ensures that a single battery failure doesn't cut power to the Pi, GSM module, or servos mid-flight.

The flight controller and motors run on a separate high-current LiPo battery — completely isolated from the Pi's power rail to prevent motor noise from affecting the mission computer.

---

## Wiring Summary

```
Raspberry Pi 4
│
├── CSI-0 (15-pin FFC) ──────────────────► ArduCam 8MP (Camera 1)
├── CSI-1 (22-pin FFC) ──────────────────► ArduCam 8MP (Camera 2)
│
├── UART (/dev/ttyAMA0) ─────────────────► Flight Controller TX/RX
│   (921600 baud, MAVLink 2)
│
├── USB (/dev/ttyUSB2) ──────────────────► SIM7600G-H USB port
│   (AT commands, 115200 baud)
│
├── I2C Bus 1 (SDA=GPIO2, SCL=GPIO3) ───► VL53L8CH (addr 0x29)
│
├── GPIO 18 (PWM) ───────────────────────► MG995 Servo 1 signal wire
├── GPIO 23 (PWM) ───────────────────────► MG995 Servo 2 signal wire
│
└── Wi-Fi (via ESP32-S3 bridge) ─────────► Operator laptop (LAN)

Flight Controller
│
├── UART ────────────────────────────────► Raspberry Pi (MAVLink)
├── ESC outputs (PWM) ───────────────────► 4× ESCs → Motors
├── GPS port ────────────────────────────► GPS/Compass module
└── Servo output Ch9 ────────────────────► MG995 Servo 2 (DO_SET_SERVO)
```

---

## ArduPilot Configuration

### Initial Setup Sequence

1. Flash ArduCopter firmware via Mission Planner (USB)
2. Frame type: Quad X — verify motor order and spin direction with motor test tool
3. Accelerometer calibration: six-position (level, nose-up, nose-down, left, right, inverted)
4. Compass calibration: onboard + external; run `compassmot` to offset motor interference
5. Radio calibration: map RC channels, set endpoints, configure failsafe → RTL
6. ESC calibration: all ESCs simultaneously for uniform throttle response

### Key Parameters

```
# MAVLink / Companion computer
SERIAL1_PROTOCOL = 2        # MAVLink 2 on UART1
SERIAL1_BAUD     = 921       # 921600 baud
SYSID_MYGCS      = 255       # Pi treated as GCS

# Navigation speeds
WPNAV_SPEED      = 800       # 8 m/s cruise
WPNAV_SPEED_DN   = 150       # 1.5 m/s descent
LAND_SPEED       = 50        # 0.5 m/s landing

# Failsafes
FS_THR_ENABLE    = 1         # RTL on RC signal loss
FENCE_ENABLE     = 1         # Geofence active
FENCE_TYPE       = 2         # Circle geofence
FENCE_RADIUS     = 500       # 500m radius
FENCE_ALT_MAX    = 50        # 50m max altitude

# Sensor fusion
EK3_ENABLE       = 1         # EKF3 active
ARMING_CHECK     = 1         # All pre-arm checks enforced
```

---

## Payload Container

A foam sheet box with a string attachment point. The string loops through the Servo 2 arm — when the servo rotates to open position, the string releases and the box drops.

Design criteria:
- Lightweight (minimises payload weight penalty)
- Shock-absorbing (foam protects contents on drop)
- Releasable by a single servo rotation
- Replaceable / low-cost per delivery
