"""
mission.py — ALMDS Mission Orchestrator

Entry point for the Autonomous Last-Mile Delivery System.
Runs the full delivery state machine from QR scan to RTL.

Usage:
    python src/mission.py

Environment:
    All configuration loaded from .env via python-dotenv.
    See .env.example for required variables.
"""

import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

from vision.scanner import QRScanner
from vision.payload import parse_payload, InvalidPayloadError
from control.mavlink import MissionController
from control.servo import ServoController
from control.tof import ToFController
from control.api import start_api_server
from comms.telemetry import TelemetryStream
from comms.notify import NotificationService

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


# ── State machine states ──────────────────────────────────────────────────────

class State:
    IDLE                   = "IDLE"
    SCANNING_PACKAGE       = "SCANNING_PACKAGE"
    VALIDATING_DELIVERY    = "VALIDATING_DELIVERY"
    LOADING_CARGO          = "LOADING_CARGO"
    UPLOADING_MISSION      = "UPLOADING_MISSION"
    PRE_ARM_CHECKS         = "PRE_ARM_CHECKS"
    ARMED_TAKEOFF          = "ARMED_TAKEOFF"
    IN_FLIGHT              = "IN_FLIGHT"
    APPROACHING_DESTINATION = "APPROACHING_DESTINATION"
    SCANNING_DROPBOX       = "SCANNING_DROPBOX"
    VERIFYING_LOCATION     = "VERIFYING_LOCATION"
    RELEASING_PAYLOAD      = "RELEASING_PAYLOAD"
    CONFIRMING_DELIVERY    = "CONFIRMING_DELIVERY"
    NOTIFYING_CUSTOMER     = "NOTIFYING_CUSTOMER"
    RETURNING_TO_BASE      = "RETURNING_TO_BASE"
    LANDED                 = "LANDED"
    ABORTED                = "ABORTED"


# ── Main mission runner ───────────────────────────────────────────────────────

def run_mission():
    log.info("ALMDS Mission Controller starting...")

    # Initialise subsystems
    scanner_dock     = QRScanner(int(os.getenv("CAMERA_DOCK_INDEX", 0)))
    scanner_inflight = QRScanner(int(os.getenv("CAMERA_INFLIGHT_INDEX", 1)))
    flight           = MissionController()
    servo            = ServoController()
    tof              = ToFController()
    telemetry        = TelemetryStream()
    notifier         = NotificationService()

    # Start Flask API in background thread (operator dashboard interface)
    start_api_server(servo=servo, flight=flight)

    state = State.IDLE
    delivery = None

    while True:
        log.info(f"State: {state}")

        # ── Gate 1: Scan package QR at docking station ────────────────────────
        if state == State.IDLE:
            state = State.SCANNING_PACKAGE

        elif state == State.SCANNING_PACKAGE:
            log.info("Camera 1 active — waiting for package QR scan...")
            payload = None
            while payload is None:
                payload = scanner_dock.scan()
                time.sleep(0.2)
            try:
                delivery = parse_payload(payload)
                log.info(f"QR decoded: delivery_id={delivery.delivery_id}")
                state = State.VALIDATING_DELIVERY
            except InvalidPayloadError as e:
                log.error(f"Invalid QR payload: {e}. Retrying...")

        # ── Gate 2: Validate delivery ID against dashboard ────────────────────
        elif state == State.VALIDATING_DELIVERY:
            if validate_with_dashboard(delivery.delivery_id):
                log.info("Delivery ID validated against dashboard.")
                state = State.LOADING_CARGO
            else:
                log.error(f"Delivery ID {delivery.delivery_id} not found in dashboard. Mission blocked.")
                state = State.ABORTED

        # ── Cargo loading (operator action via dashboard API) ─────────────────
        elif state == State.LOADING_CARGO:
            log.info("Waiting for operator to load cargo via dashboard...")
            # Servo 1 (cargo door) is controlled by the Flask API endpoint.
            # Mission proceeds when operator signals cargo loaded via API.
            wait_for_cargo_loaded()
            state = State.UPLOADING_MISSION

        # ── Build and upload MAVLink mission ──────────────────────────────────
        elif state == State.UPLOADING_MISSION:
            flight.connect()
            flight.upload_mission(
                lat=delivery.gps.lat,
                lon=delivery.gps.lon,
                alt=float(os.getenv("CRUISE_ALTITUDE_M", 15))
            )
            log.info("MAVLink mission uploaded.")
            state = State.PRE_ARM_CHECKS

        # ── Pre-arm safety checks ─────────────────────────────────────────────
        elif state == State.PRE_ARM_CHECKS:
            if flight.pre_arm_check():
                log.info("All pre-arm checks passed.")
                state = State.ARMED_TAKEOFF
            else:
                log.error("Pre-arm checks failed. Aborting.")
                state = State.ABORTED

        # ── Arm and take off ──────────────────────────────────────────────────
        elif state == State.ARMED_TAKEOFF:
            telemetry.start(delivery.delivery_id)
            flight.arm_and_takeoff(float(os.getenv("CRUISE_ALTITUDE_M", 15)))
            log.info("Airborne. Autonomous navigation active.")
            state = State.IN_FLIGHT

        # ── Monitor flight to destination ─────────────────────────────────────
        elif state == State.IN_FLIGHT:
            lat, lon, alt = flight.monitor_position()
            if flight.near_destination(lat, lon, delivery.gps.lat, delivery.gps.lon):
                state = State.APPROACHING_DESTINATION
            time.sleep(1)

        # ── Descend and scan drop-box ─────────────────────────────────────────
        elif state == State.APPROACHING_DESTINATION:
            log.info("Approaching destination. Camera 2 active.")
            state = State.SCANNING_DROPBOX

        elif state == State.SCANNING_DROPBOX:
            dropbox_payload = None
            while dropbox_payload is None:
                if tof.at_drop_height():
                    dropbox_payload = scanner_inflight.scan()
                time.sleep(0.5)
            state = State.VERIFYING_LOCATION

        # ── Gate 3: Verify drop-box identity ─────────────────────────────────
        elif state == State.VERIFYING_LOCATION:
            if dropbox_payload.get("delivery_id") == delivery.delivery_id:
                log.info("Drop-box verified. Releasing payload.")
                state = State.RELEASING_PAYLOAD
            else:
                log.warning("Drop-box ID mismatch. Re-navigating...")
                flight.guided_goto(delivery.gps.lat, delivery.gps.lon, delivery.gps.alt)
                state = State.SCANNING_DROPBOX

        # ── Release payload ───────────────────────────────────────────────────
        elif state == State.RELEASING_PAYLOAD:
            flight.release_payload()
            delivery.delivered_at = datetime.utcnow()
            state = State.CONFIRMING_DELIVERY

        # ── Confirm delivery and update dashboard ─────────────────────────────
        elif state == State.CONFIRMING_DELIVERY:
            confirm_delivery(delivery)
            log.info(f"Delivery {delivery.delivery_id} confirmed.")
            state = State.NOTIFYING_CUSTOMER

        # ── Notify customer ───────────────────────────────────────────────────
        elif state == State.NOTIFYING_CUSTOMER:
            notifier.notify_delivery(delivery)
            state = State.RETURNING_TO_BASE

        # ── Return to base ────────────────────────────────────────────────────
        elif state == State.RETURNING_TO_BASE:
            flight.return_to_launch()
            log.info("RTL initiated. Returning to docking station.")
            state = State.LANDED

        elif state == State.LANDED:
            telemetry.stop()
            log.info("Mission complete.")
            break

        elif state == State.ABORTED:
            telemetry.stop()
            log.error("Mission aborted.")
            break


# ── Helpers ───────────────────────────────────────────────────────────────────

def validate_with_dashboard(delivery_id: str) -> bool:
    """Check delivery_id against the dashboard backend."""
    import requests
    url = f"{os.getenv('DASHBOARD_URL')}/api/deliveries/{delivery_id}"
    headers = {"X-API-Key": os.getenv("DASHBOARD_API_KEY")}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def wait_for_cargo_loaded():
    """Block until the operator signals cargo is loaded via the Flask API."""
    # The Flask API sets a shared flag when POST /api/servo/cargo-door {"action":"close"} is called
    # after the door was opened. This is a simplified polling loop.
    from control.api import cargo_loaded_event
    cargo_loaded_event.wait()
    cargo_loaded_event.clear()


def confirm_delivery(delivery):
    """Update delivery record in dashboard to Delivered."""
    import requests
    url = f"{os.getenv('DASHBOARD_URL')}/api/deliveries/{delivery.delivery_id}/confirm"
    headers = {"X-API-Key": os.getenv("DASHBOARD_API_KEY")}
    data = {"delivered_at": delivery.delivered_at.isoformat()}
    try:
        requests.post(url, json=data, headers=headers, timeout=5)
    except requests.RequestException as e:
        log.warning(f"Failed to confirm delivery on dashboard: {e}")


if __name__ == "__main__":
    run_mission()
