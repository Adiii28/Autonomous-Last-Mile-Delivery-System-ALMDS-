# System Design

Software architecture, data models, module responsibilities, API contracts, and design decisions.

---

## Module Structure

```
src/
├── mission.py          ← Entry point. Orchestrates the full delivery lifecycle.
├── vision/
│   ├── __init__.py
│   ├── scanner.py      ← QR capture and decode (OpenCV + pyzbar)
│   └── payload.py      ← QR payload parsing and validation
├── comms/
│   ├── __init__.py
│   ├── gsm.py          ← SIM7600G-H AT command interface
│   ├── telemetry.py    ← 4G telemetry stream to dashboard
│   └── notify.py       ← SMS, call, and email dispatch
└── control/
    ├── __init__.py
    ├── servo.py        ← MG995 PWM control via pigpio
    ├── tof.py          ← VL53L8CH I2C driver and descent logic
    ├── mavlink.py      ← DroneKit mission builder and flight commands
    └── api.py          ← Flask HTTP API for operator dashboard
```

---

## mission.py — Delivery Lifecycle

`mission.py` is the top-level orchestrator. It runs the full delivery state machine from QR scan to RTL.

### State Machine

```
IDLE
  │
  ▼ (package placed, Camera 1 active)
SCANNING_PACKAGE
  │ QR decoded
  ▼
VALIDATING_DELIVERY
  │ delivery_id confirmed in dashboard
  ▼
LOADING_CARGO
  │ operator opens door via API, loads package, closes door
  ▼
UPLOADING_MISSION
  │ MAVLink mission built from QR GPS, uploaded to flight controller
  ▼
PRE_ARM_CHECKS
  │ GPS fix, EKF ok, battery ok
  ▼
ARMED_TAKEOFF
  │ vehicle.armed = True, simple_takeoff(15)
  ▼
IN_FLIGHT
  │ AUTO mode, monitoring position
  ▼
APPROACHING_DESTINATION
  │ within loiter radius of delivery GPS
  ▼
SCANNING_DROPBOX
  │ Camera 2 active, ToF descending
  ▼
VERIFYING_LOCATION
  │ drop-box QR matches delivery_id
  ▼
RELEASING_PAYLOAD
  │ DO_SET_SERVO command sent
  ▼
CONFIRMING_DELIVERY
  │ drop-box confirms receipt, dashboard updated
  ▼
NOTIFYING_CUSTOMER
  │ SMS + call + email dispatched
  ▼
RETURNING_TO_BASE
  │ RTL mode
  ▼
LANDED
```

---

## vision/ — QR Pipeline

### scanner.py

Wraps OpenCV frame capture and pyzbar decode into a simple polling interface.

```python
class QRScanner:
    def __init__(self, camera_index: int, resolution: tuple):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    def scan(self) -> dict | None:
        """
        Captures a frame and attempts QR decode.
        Returns parsed payload dict on success, None on failure.
        """
        ret, frame = self.cap.read()
        if not ret:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        codes = pyzbar.decode(gray)
        if codes:
            return json.loads(codes[0].data.decode('utf-8'))
        return None
```

Camera 1 (docking station) scans at 200ms intervals. Camera 2 (in-flight) scans at 500ms intervals — slower because the drone is moving and frames need stabilisation time.

### payload.py

Validates the decoded QR JSON against the expected schema:

```python
QR_SCHEMA = {
    "delivery_id": str,
    "gps": {
        "lat": float,
        "lon": float,
        "alt": float
    },
    "customer": {
        "phone": str,
        "email": str
    }
}
```

Raises `InvalidPayloadError` if any field is missing or the wrong type. This prevents a malformed QR from causing a mission to arm with bad GPS coordinates.

---

## control/ — Flight & Hardware Control

### mavlink.py

Wraps DroneKit into a clean mission interface.

Key methods:

```python
class MissionController:
    def connect(self) -> None
        # Connects to flight controller, waits for heartbeat

    def pre_arm_check(self) -> bool
        # Validates GPS fix, EKF health, battery voltage

    def upload_mission(self, lat: float, lon: float, alt: float) -> None
        # Builds and uploads 4-waypoint MAVLink mission

    def arm_and_takeoff(self, target_alt: float) -> None
        # Arms vehicle, initiates takeoff, waits for altitude

    def monitor_position(self) -> tuple[float, float, float]
        # Returns current lat, lon, alt

    def guided_goto(self, lat: float, lon: float, alt: float) -> None
        # Switches to GUIDED mode, sends position target

    def release_payload(self) -> None
        # Sends DO_SET_SERVO MAVLink command

    def return_to_launch(self) -> None
        # Sets vehicle mode to RTL
```

### servo.py

Controls MG995 servos via `pigpio` daemon. Uses hardware PWM for precise 50Hz timing — software PWM on the Pi can jitter under CPU load.

```python
class ServoController:
    FREQ_HZ = 50
    PULSE_CLOSED_US = 1000   # 1.0 ms
    PULSE_OPEN_US   = 2000   # 2.0 ms

    def open(self, pin: int) -> None
    def close(self, pin: int) -> None
    def set_pulse(self, pin: int, pulse_us: int) -> None
```

### tof.py

Reads the VL53L8CH 8×8 ranging grid over I2C and implements the descent hold logic.

```python
class ToFController:
    def get_zone_distances(self) -> list[list[int]]
        # Returns 8×8 grid of distances in mm

    def get_median_distance(self) -> int
        # Median of all 64 zones — robust to outliers

    def surface_is_level(self, tolerance_mm: int = 50) -> bool
        # True if zone variance is within tolerance

    def at_drop_height(self) -> bool
        # True if median distance == TOF_DROP_HEIGHT_CM ± tolerance
```

The drone holds position until both `surface_is_level()` and `at_drop_height()` return `True` before the payload is released.

### api.py

Flask HTTP API running on the Pi. Allows the operator dashboard to trigger servo actuation and read system status.

```
GET  /api/status
     → { "state": "IDLE", "battery": 15.1, "gps_fix": 3, "ekf_ok": true }

POST /api/servo/cargo-door
     Body: { "action": "open" | "close" }
     → { "success": true }

POST /api/servo/payload-drop
     Body: { "action": "release" }
     → { "success": true }

GET  /api/delivery/current
     → { "delivery_id": "DLV-...", "status": "IN_FLIGHT", "gps": {...} }

POST /api/mission/abort
     → Triggers RTL immediately
```

---

## comms/ — Communication Layer

### gsm.py

Low-level AT command interface for the SIM7600G-H over serial.

```python
class GSMController:
    def send_at(self, command: str, timeout: float = 1.0) -> str
        # Sends AT command, returns response string

    def check_signal(self) -> int
        # AT+CSQ → returns RSSI (0-31, 99=unknown)

    def send_sms(self, number: str, message: str) -> bool
        # AT+CMGS

    def make_call(self, number: str, duration_s: int = 10) -> bool
        # AT+ATD → waits → AT+CHUP

    def open_tcp(self, host: str, port: int) -> bool
        # AT+CIPSTART

    def send_tcp(self, data: str) -> bool
        # AT+CIPSEND
```

### telemetry.py

Streams a MAVLink telemetry subset to the operator dashboard over 4G TCP every 2 seconds.

Payload format:
```json
{
  "delivery_id": "DLV-20260321-0042",
  "timestamp": "2026-03-21T14:32:10Z",
  "lat": 13.0067,
  "lon": 74.7942,
  "alt": 14.8,
  "groundspeed": 7.9,
  "battery_voltage": 14.6,
  "flight_mode": "AUTO",
  "ekf_ok": true,
  "state": "IN_FLIGHT"
}
```

### notify.py

Dispatches customer notifications on delivery confirmation.

```python
class NotificationService:
    def notify_delivery(self, delivery: DeliveryRecord) -> None:
        if config.sms_enabled:
            self.gsm.send_sms(delivery.customer_phone, self._sms_body(delivery))
        if config.call_enabled:
            self.gsm.make_call(delivery.customer_phone)
```

---

## Data Models

### DeliveryRecord

```python
@dataclass
class DeliveryRecord:
    delivery_id: str
    status: str                  # PENDING | IN_FLIGHT | DELIVERED | FAILED
    gps: GPSCoordinate
    customer_phone: str
    customer_email: str
    scanned_at: datetime
    delivered_at: datetime | None
```

### GPSCoordinate

```python
@dataclass
class GPSCoordinate:
    lat: float
    lon: float
    alt: float
```

---

## Design Decisions

### Why DroneKit over raw pymavlink?

DroneKit provides a clean Python abstraction over MAVLink — `vehicle.armed`, `vehicle.mode`, `vehicle.commands.upload()` — that makes mission logic readable and testable. Raw pymavlink requires manually constructing and parsing binary MAVLink frames, which adds complexity without benefit at this level.

### Why pigpio over RPi.GPIO for servos?

`RPi.GPIO` software PWM can jitter by ±1ms under CPU load — enough to cause servo twitching or missed positions. `pigpio` uses a hardware DMA-based PWM engine that maintains precise 50Hz timing regardless of CPU load. For servo control, timing precision directly affects mechanical reliability.

### Why two separate cameras instead of one?

The two cameras serve fundamentally different use cases that require different capture parameters:

- Camera 1 needs high resolution and fixed focus for close-range stationary scanning
- Camera 2 needs wide exposure range and motion tolerance for airborne scanning

A single camera would require runtime reconfiguration between these modes, adding latency and complexity. Two dedicated cameras with pre-tuned profiles is simpler and more reliable.

### Why foam sheet for the payload container?

Weight is the primary constraint. Every gram of payload container is a gram less of deliverable cargo. Foam sheet is:
- Extremely lightweight
- Shock-absorbing (protects contents on drop)
- Cheap and replaceable
- Easy to attach to the servo release mechanism

A rigid box would add unnecessary weight and complexity.
