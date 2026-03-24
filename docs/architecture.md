# System Architecture

This document covers how all components of the ALMDS interact — from the moment a package is scanned to the moment the drone lands back at base.

---

## Architectural Philosophy

The system is split into two distinct layers of responsibility:

- **Mission layer (Raspberry Pi)** — all smart logic: QR parsing, delivery validation, servo control, customer notification, telemetry streaming
- **Flight layer (ArduPilot)** — all real-time flight control: motor mixing, PID stabilisation, GPS navigation, sensor fusion

The Pi never directly controls motors. It sends high-level MAVLink commands and ArduPilot executes them. This separation means mission logic can be developed and tested independently of the flight controller.

---

## Component Interaction Map

```
                        ┌─────────────────────────────────────────┐
                        │           Raspberry Pi 4                │
                        │         (Mission Computer)              │
                        │                                         │
  Camera 1 ──CSI──────► │  QR Pipeline     Flask/FastAPI          │
  Camera 2 ──CSI──────► │  (OpenCV+pyzbar) (Servo HTTP API)       │
                        │       │                │                │
  VL53L8CH ──I2C──────► │  ToF Driver      Servo PWM Driver       │──GPIO──► MG995 × 2
                        │       │                                 │
  SIM7600G-H ──UART───► │  GSM/4G Driver                          │
                        │       │                                 │
                        │  DroneKit-Python ◄──────────────────────┤
                        │       │                                 │
                        └───────┼─────────────────────────────────┘
                                │ MAVLink 2 · UART · 921600 baud
                                ▼
                        ┌───────────────────┐
                        │  Flight Controller │
                        │  ArduCopter        │
                        │                   │
                        │  EKF3 fusion       │◄── GPS + IMU + Baro + Compass
                        │  PID stabiliser    │──► ESCs → Motors
                        │  Waypoint nav      │
                        │  Failsafe logic    │
                        └───────────────────┘

                                                    ┌──────────────┐
  SIM7600G-H ──4G──────────────────────────────────► Operator      │
                                                    │ Dashboard    │
                                                    └──────────────┘

  ESP32-S3 ──Wi-Fi 6──────────────────────────────► Operator       │
                                                    │ Laptop (LAN) │
                                                    └──────────────┘

  SIM7600G-H ──4G──► SMS / Call / Email ──────────► Customer
```

---

## MAVLink Communication Flow

The Raspberry Pi communicates with ArduPilot using **MAVLink 2** over a UART serial link at 921600 baud. DroneKit-Python abstracts the raw MAVLink messages into a Python API.

### Connection & Health Check

```
Pi boots
  └── DroneKit connects: vehicle = connect('/dev/ttyAMA0', baud=921600)
        └── Waits for HEARTBEAT from flight controller (1 Hz)
              └── Polls health:
                    ├── vehicle.gps_0.fix_type >= 3   (3D GPS fix)
                    ├── vehicle.ekf_ok == True         (EKF healthy)
                    └── vehicle.battery.voltage > 14.2V
```

### Mission Upload

GPS coordinates decoded from the QR code are assembled into a `CommandSequence` and uploaded before each flight:

```
WP 0  MAV_CMD_NAV_TAKEOFF          alt=15m AGL
WP 1  MAV_CMD_NAV_WAYPOINT         lat, lon, alt  ← from QR
WP 2  MAV_CMD_NAV_LOITER_UNLIM     ← hold for Camera 2 scan
WP 3  MAV_CMD_NAV_RETURN_TO_LAUNCH ← auto-RTL
```

If Camera 2 scan requires a position correction, the Pi switches to GUIDED mode and sends a `SET_POSITION_TARGET_GLOBAL_INT` message before resuming AUTO.

### Payload Release

The payload drop is triggered via a MAVLink `DO_SET_SERVO` command sent from the Pi:

```python
vehicle.message_factory.command_long_send(
    0, 0,
    mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
    0,
    SERVO_CHANNEL,   # servo output channel (e.g. 9)
    OPEN_PWM,        # 2000 µs = open position
    0, 0, 0, 0, 0
)
```

This routes through ArduPilot's servo output, ensuring the drop is synchronised with the flight controller's state machine.

---

## Three-Gate Authentication Pipeline

Every delivery must pass three sequential gates. Failure at any gate halts the mission.

### Gate 1 — Origin Check (Docking Station)

- Camera 1 captures frames continuously at the docking station
- pyzbar attempts QR decode on each frame
- On success: JSON payload extracted → `delivery_id`, `gps`, `customer`
- On failure after N retries: operator alert triggered via dashboard

### Gate 2 — Dashboard Validation (Pre-arm)

- `delivery_id` from QR sent to dashboard backend via HTTP GET
- Dashboard checks against active delivery records in its database
- Match found: mission proceeds, GPS coordinates loaded into MAVLink mission
- No match: mission blocked, mismatch flagged in dashboard with timestamp

### Gate 3 — Destination Verification (In-flight)

- Camera 2 begins scanning as drone descends toward delivery GPS coordinates
- pyzbar decodes drop-box QR
- Decoded `delivery_id` compared against the active mission's ID
- Match: payload released
- No match: Pi switches to GUIDED mode, adjusts position, retries scan

---

## Telemetry Architecture

Two parallel telemetry channels operate simultaneously during flight:

### 4G Telemetry (SIM7600G-H)

- MAVLink telemetry subset tunnelled over TCP/IP via 4G
- Fields streamed: `lat`, `lon`, `alt`, `groundspeed`, `battery_voltage`, `flight_mode`, `ekf_ok`
- Update rate: every 2 seconds
- Used for: beyond-line-of-sight operator visibility, delivery record sync

### Wi-Fi Telemetry (ESP32-S3)

- Local Wi-Fi 6 bridge between Pi and operator laptop
- Used for: docking station operations, servo control, pre-flight checks
- Dual IPEX antennas compensate for RF interference from the metal drone frame
- Falls back to 4G once drone is airborne and out of Wi-Fi range

---

## Failsafe Hierarchy

ArduPilot enforces a layered failsafe system:

| Trigger | Response |
|---|---|
| RC signal lost (`FS_THR_ENABLE=1`) | Immediate RTL |
| Geofence breached (`FENCE_ENABLE=1`) | Auto-RTL |
| Battery critical voltage | Land in place |
| EKF variance too high | Hold position / Land |
| GPS fix lost | Hold position (baro alt hold) |

The Pi adds a software-level failsafe: if the dashboard connection is lost before arming, the mission is blocked. If lost mid-flight, the Pi logs the event and continues — the flight controller's hardware failsafes remain active regardless.

---

## Data Flow Summary

```
QR Scan
  │
  ├── delivery_id ──────────────────────► Dashboard validation
  ├── gps (lat/lon/alt) ────────────────► MAVLink mission builder
  └── customer (phone/email) ───────────► Notification queue

Mission execution
  │
  ├── DroneKit commands ────────────────► ArduPilot (MAVLink)
  ├── Servo commands ───────────────────► MG995 via GPIO PWM
  ├── ToF readings ─────────────────────► Altitude hold logic
  └── Telemetry ────────────────────────► Dashboard (4G TCP)

Delivery confirmed
  │
  ├── Dashboard record ─────────────────► Status: "Delivered"
  └── SIM7600G-H ───────────────────────► SMS + Call + Email → Customer
```
