import requests
import os

def turn_on_light():
    url = f"http://10.10.10.142:8123/api/services/switch/turn_on"
    headers = {
        "Authorization": f"Bearer {os.getenv("HASS_API_KEY")}",
        "Content-Type": "application/json",
    } 
    data = {
        "entity_id":"switch.power_monitor_switch_1"
    }
    response = requests.post(url, headers=headers, json=data)
    return response.status_code  if response.ok else response.text
 
def turn_off_light():
    url = f"http://10.10.10.142:8123/api/services/switch/turn_off"
    headers = {
        "Authorization": f"Bearer {os.getenv("HASS_API_KEY")}",
        "Content-Type": "application/json",
    }
    data = {
        "entity_id":"switch.power_monitor_switch_1"
    }
    response = requests.post(url, headers=headers, json=data)
    return response.status_code if response.ok else response.text
 
