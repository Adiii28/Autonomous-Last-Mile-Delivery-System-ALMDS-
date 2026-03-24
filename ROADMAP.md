# Roadmap

Planned improvements, research directions, and known limitations.

---

## Current Limitations

**No obstacle avoidance** — the drone relies on pre-planned altitude and assumes clear airspace. Any obstacle in the flight path is a collision risk. The system is currently only safe in controlled, known environments.

**Single-drone operation** — the current architecture supports one active delivery at a time. There is no fleet coordination, route optimisation, or conflict resolution for shared airspace.

**Plaintext QR payloads** — QR codes are unencrypted JSON. A malicious actor could create a spoofed QR code with fabricated GPS coordinates and a valid-looking delivery ID, potentially redirecting a delivery.

**Weather-blind** — the system has no awareness of wind speed, precipitation, or visibility. Missions are not automatically paused in unsafe conditions.

**Manual battery swap** — the drone must be manually returned to base and batteries swapped between deliveries. There is no automated charging or hot-swap capability.

**Fixed delivery altitude** — the cruise altitude is a single preset value. There is no terrain-following or dynamic altitude adjustment for varying ground elevation along the route.

---

## Near-Term (v1.1)

### Obstacle Avoidance
Add a depth camera (Intel RealSense D435 or similar) or stereo vision module to the drone. Implement a reactive avoidance layer that can detect and navigate around obstacles in the flight path without aborting the mission.

The avoidance layer would sit between the mission planner and the MAVLink command interface — intercepting waypoint commands and adjusting them in real time based on depth data.

### Encrypted QR Payloads
Sign QR payloads with an HMAC or asymmetric key pair. The docking station generates QR codes using a private key; the drone verifies the signature before accepting the payload. This prevents spoofing and creates a tamper-evident delivery chain.

```
QR payload (current):   { "delivery_id": "...", "gps": {...}, ... }
QR payload (encrypted): { "data": "<base64>", "sig": "<hmac_sha256>" }
```

### Improved Drop-Zone Detection
Replace the single QR code on the drop-box with an ArUco marker or AprilTag. These are more robust to partial occlusion, motion blur, and varying lighting than QR codes, and provide 6-DOF pose estimation — allowing the drone to align precisely above the drop-box before releasing.

---

## Medium-Term (v2.0)

### Multi-Drone Fleet Management
A centralised cloud dashboard that manages multiple drones simultaneously:
- Route optimisation across a fleet (minimise total delivery time)
- Airspace conflict detection and resolution (altitude separation, time-based scheduling)
- Centralised delivery record management
- Per-drone health monitoring and maintenance alerts

### Weather-Aware Mission Planning
Integrate a real-time weather API (OpenWeatherMap or similar). Before arming, the system checks:
- Wind speed < threshold (e.g. 10 m/s)
- No precipitation
- Visibility > minimum
- Temperature within battery operating range

Missions are automatically queued and retried when conditions improve.

### Terrain-Following Navigation
Use SRTM elevation data or a real-time terrain API to adjust cruise altitude dynamically along the route, maintaining a constant height above ground level rather than a fixed MSL altitude. Critical for deliveries across varied terrain.

---

## Long-Term (v3.0)

### Solar Charging Dock
A solar-powered docking station with automated battery charging or hot-swap capability. Enables continuous autonomous operation without manual intervention between deliveries.

### Computer Vision Package Identification
Replace QR-code-only verification with a computer vision model that can identify packages by visual features (size, colour, label). This adds a redundant verification layer and enables handling of packages where the QR code is damaged or obscured.

### End-to-End Delivery Encryption
Full encryption of the delivery chain:
- Encrypted QR payloads (asymmetric key)
- Encrypted telemetry stream (TLS over 4G)
- Signed delivery confirmations (non-repudiation)
- Audit log stored on tamper-evident backend

### Regulatory Compliance Module
A configurable compliance layer that enforces jurisdiction-specific rules:
- No-fly zones (airports, restricted airspace)
- Maximum altitude limits
- Required transponder broadcasts (ADS-B out)
- Automatic mission abort on airspace violation
