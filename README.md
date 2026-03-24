# Autonomous Last-Mile Delivery System (ALMDS)

> A fully autonomous delivery UAV that reads its destination from a package QR code, flies there, verifies the drop-box, releases the payload, notifies the customer over 4G, and returns to base — no human intervention required after the initial scan.

---

## What This Is

ALMDS is an end-to-end autonomous delivery pipeline built on a quadcopter UAV. The system eliminates human dependency at both the dispatch and delivery ends. A single QR scan at the docking station is all it takes to initiate a complete delivery cycle.

The package itself carries the mission. GPS coordinates, delivery ID, and customer contact details are all encoded in the QR code attached to the package. The drone reads this, builds a MAVLink waypoint mission on the fly, executes it, and handles everything through to customer notification.

---

## Key Capabilities

- **QR-driven mission planning** — destination GPS injected at runtime from the package, no pre-programmed routes
- **Triple-gate authentication** — package verified at origin, cross-checked against dashboard, re-verified at destination
- **Autonomous payload release** — servo-actuated drop mechanism triggered via MAVLink `DO_SET_SERVO`
- **4G telemetry** — live positional data streamed to operator dashboard beyond Wi-Fi range
- **Customer notification** — SMS, voice call, and email dispatched on delivery confirmation via SIM7600G-H
- **ToF precision descent** — 8×8 multi-zone ranging for terrain-aware final approach

---

## System Overview

```
[Package QR Scan]
       │
       ▼
[Gate 1: QR decoded?] ──No──► Retry / Alert operator
       │ Yes
       ▼
[Gate 2: ID in dashboard?] ──No──► Block / Flag mismatch
       │ Yes
       ▼
[Cargo loaded · Mission uploaded · Drone armed]
       │
       ▼
[Autonomous flight to GPS destination]
       │
       ▼
[Gate 3: Drop-box QR confirmed?] ──No──► Re-navigate (GUIDED mode)
       │ Yes
       ▼
[Payload released · Customer notified · RTL]
```

---

## Hardware at a Glance

| Component | Part |
|---|---|
| Mission Computer | Raspberry Pi 4, 4GB RAM |
| Flight Controller | Pixhawk / Cube Orange (ArduCopter) |
| Cameras | ArduCam 8MP × 2 (CSI-2) |
| Servos | MG995 × 2 (cargo door + payload drop) |
| 4G Module | SIM7600G-H |
| Wi-Fi Bridge | ESP32-S3 (Wi-Fi 6, dual IPEX antennas) |
| ToF Sensor | VL53L8CH (8×8 zone ranging) |
| Drop-box Controller | ESP32-S3 |

---

## Repository Structure

```
ALMDS/
├── README.md               ← You are here
├── LICENSE
├── .gitignore
├── requirements.txt        ← Python dependencies
├── .env.example            ← Environment variable template
├── SETUP.md                ← Hardware wiring + software setup guide
├── ROADMAP.md              ← Planned features and improvements
├── config/
│   └── example.json        ← Mission and hardware configuration
├── docs/
│   ├── architecture.md     ← Full system architecture deep-dive
│   ├── hardware.md         ← Hardware stack, wiring, and specs
│   └── system-design.md    ← Software design, data flow, API contracts
├── media/
│   ├── demo.mp4            ← Flight demonstration
│   └── diagram.png         ← System architecture diagram
└── src/
    ├── mission.py          ← Main mission orchestrator (entry point)
    ├── vision/             ← QR scanning pipeline (OpenCV + pyzbar)
    ├── comms/              ← 4G telemetry, SMS/call, dashboard stream
    └── control/            ← Servo PWM control, Flask API, MAVLink bridge
```

---

## Quick Start

See [SETUP.md](./SETUP.md) for full hardware wiring and environment setup.

```bash
git clone https://github.com/your-org/ALMDS.git
cd ALMDS
pip install -r requirements.txt
cp .env.example .env
# edit .env with your SIM, dashboard, and serial port config
python src/mission.py
```

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](./docs/architecture.md) | System architecture, MAVLink flow, component interaction |
| [docs/hardware.md](./docs/hardware.md) | Full hardware stack, wiring diagrams, calibration |
| [docs/system-design.md](./docs/system-design.md) | Software design, QR pipeline, API contracts, data models |
| [SETUP.md](./SETUP.md) | Step-by-step setup from scratch |
| [ROADMAP.md](./ROADMAP.md) | Planned features and future scope |

---

## License

MIT — see [LICENSE](./LICENSE)
