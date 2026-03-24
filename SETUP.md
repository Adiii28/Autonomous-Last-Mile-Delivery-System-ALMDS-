# Setup Guide

Step-by-step instructions to get ALMDS running from scratch — hardware wiring, OS setup, software installation, and first flight checklist.

---

## Prerequisites

- Raspberry Pi 4 (4GB) with Raspberry Pi OS Lite 64-bit (headless)
- Python 3.11+ installed on the Pi
- ArduCopter firmware flashed on the flight controller (Pixhawk / Cube Orange)
- SIM card with data + voice + SMS activated in the SIM7600G-H
- Both ArduCam 8MP cameras connected via CSI ribbon cables
- `pigpio` daemon installed and enabled on the Pi

---

## 1. Raspberry Pi OS Setup

```bash
# Enable I2C and camera interfaces
sudo raspi-config
# → Interface Options → I2C → Enable
# → Interface Options → Camera → Enable (legacy camera stack)
# → Interface Options → Serial Port → Disable login shell, Enable serial hardware

# Enable pigpio daemon on boot
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# Verify cameras are detected
vcgencmd get_camera
# Expected: supported=2 detected=2
```

---

## 2. Clone and Install

```bash
git clone https://github.com/your-org/ALMDS.git
cd ALMDS

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 3. Environment Configuration

```bash
cp .env.example .env
nano .env
```

Fill in:
- `MAVLINK_PORT` — check with `ls /dev/tty*` after connecting flight controller
- `GSM_PORT` — check with `ls /dev/ttyUSB*` after connecting SIM7600G-H
- `DASHBOARD_URL` and `DASHBOARD_API_KEY` — your backend endpoint
- `SERVO_CARGO_DOOR_PIN` and `SERVO_PAYLOAD_DROP_PIN` — BCM GPIO numbers

---

## 4. Hardware Connections

### Flight Controller → Pi

Connect flight controller UART TX/RX to Pi GPIO 14/15 (UART0):

```
Flight Controller TELEM2 TX  →  Pi GPIO 15 (RXD)
Flight Controller TELEM2 RX  →  Pi GPIO 14 (TXD)
Flight Controller GND        →  Pi GND
```

Set ArduPilot parameters:
```
SERIAL1_PROTOCOL = 2
SERIAL1_BAUD     = 921
SYSID_MYGCS      = 255
```

### SIM7600G-H → Pi

Connect via USB (recommended) or UART. USB appears as `/dev/ttyUSB2` typically.

### VL53L8CH → Pi

```
VL53L8CH SDA  →  Pi GPIO 2 (SDA1)
VL53L8CH SCL  →  Pi GPIO 3 (SCL1)
VL53L8CH VIN  →  Pi 3.3V
VL53L8CH GND  →  Pi GND
```

Verify detection:
```bash
i2cdetect -y 1
# Should show device at address 0x29
```

### Servos → Pi

```
Servo 1 signal  →  Pi GPIO 18
Servo 2 signal  →  Pi GPIO 23
Servo GND       →  Pi GND (shared ground)
Servo VCC       →  External 5V supply (NOT Pi 5V pin — servos draw too much current)
```

### Cameras → Pi

- Camera 1: CSI-0 port (15-pin FFC cable)
- Camera 2: CSI-1 port (22-pin FFC cable)

Ensure ribbon cables are fully seated and the locking tab is closed.

---

## 5. ArduPilot Calibration

Complete these in Mission Planner before first flight:

1. **Frame type**: Quad X — verify motor order with motor test
2. **Accelerometer**: six-position calibration
3. **Compass**: onboard + external; run `compassmot`
4. **Radio**: map channels, set endpoints, failsafe → RTL
5. **ESC**: simultaneous calibration for uniform throttle

Set all parameters from [docs/hardware.md](./docs/hardware.md#key-parameters).

---

## 6. Test Each Subsystem

```bash
# Test MAVLink connection
python3 -c "
from dronekit import connect
v = connect('/dev/ttyAMA0', baud=921600, wait_ready=True)
print('GPS fix:', v.gps_0.fix_type)
print('Battery:', v.battery.voltage)
v.close()
"

# Test Camera 1 QR scan
python3 -c "
from src.vision.scanner import QRScanner
s = QRScanner(camera_index=0, resolution=(1920,1080))
print('Scanning... hold QR code in front of Camera 1')
import time
for _ in range(30):
    result = s.scan()
    if result:
        print('Decoded:', result)
        break
    time.sleep(0.2)
"

# Test servo movement
python3 -c "
from src.control.servo import ServoController
s = ServoController()
s.open(18)   # cargo door open
import time; time.sleep(1)
s.close(18)  # cargo door close
"

# Test GSM signal
python3 -c "
from src.comms.gsm import GSMController
g = GSMController('/dev/ttyUSB2')
print('Signal quality:', g.check_signal())
"
```

---

## 7. Run the Mission

```bash
source venv/bin/activate
python src/mission.py
```

The system will:
1. Start the Flask API server (operator dashboard interface)
2. Activate Camera 1 and begin scanning for a package QR
3. Wait for operator to place and scan a package

---

## Pre-Flight Checklist

Before every flight, verify:

- [ ] GPS fix type ≥ 3 (3D fix, ≥ 8 satellites)
- [ ] EKF status: OK
- [ ] Battery voltage above minimum threshold
- [ ] Both cameras detected and returning frames
- [ ] SIM7600G-H signal quality > 10
- [ ] Servo 1 and Servo 2 respond to open/close commands
- [ ] ToF sensor returning valid readings at I2C address 0x29
- [ ] Dashboard connection confirmed
- [ ] Geofence parameters set in ArduPilot
- [ ] Payload container attached to Servo 2 release mechanism
- [ ] Cargo door closed and latched before arming
