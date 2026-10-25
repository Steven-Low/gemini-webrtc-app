import os

import requests


DEFAULT_HASS_URL = "http://10.10.10.142:8123"
SWITCH_ENTITY_ID = "switch.power_monitor_switch_1"
REQUEST_TIMEOUT_SECONDS = 10


def _call_switch_service(service):
    """Call a Home Assistant switch service and return its status or error."""
    token = os.getenv("HASS_API_KEY")
    if not token:
        return "HASS_API_KEY is not configured"

    base_url = os.getenv("HASS_URL", DEFAULT_HASS_URL).rstrip("/")
    url = f"{base_url}/api/services/switch/{service}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        url,
        headers=headers,
        json={"entity_id": SWITCH_ENTITY_ID},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return response.status_code if response.ok else response.text


def turn_on_light():
    return _call_switch_service("turn_on")


def turn_off_light():
    return _call_switch_service("turn_off")
