"""Virtual actuator node.

Subscribe lệnh điều khiển từ gateway, cập nhật trạng thái fan/purifier/mist/board,
publish lại trạng thái và ghi log.
"""
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

CITY_ID = os.getenv("CITY_ID", "hanoi")
STATION_ID = os.getenv("STATION_ID", "station-01")
DEVICE_ID = os.getenv("DEVICE_ID", f"actuator-{STATION_ID}")
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

CMD_TOPIC = f"city/{STATION_ID}/actuator/command"
STATUS_TOPIC = f"city/{STATION_ID}/actuator/status"

# Trạng thái hiện tại của các thiết bị
STATE = {
    "fan": "off",       # off | on | max
    "purifier": "off",  # off | on
    "mist": "off",      # off | on
    "board": "Good",    # Good | Moderate | Unhealthy | Very Unhealthy
}
last_reason = "init"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish_status(client):
    payload = {
        "device_id": DEVICE_ID,
        "station_id": STATION_ID,
        "fan": STATE["fan"],
        "purifier": STATE["purifier"],
        "mist": STATE["mist"],
        "board": STATE["board"],
        "last_command_reason": last_reason,
        "timestamp": now_iso(),
    }
    client.publish(STATUS_TOPIC, json.dumps(payload), qos=1, retain=True)
    print(f"[{DEVICE_ID}] status -> {payload}", flush=True)


def apply_command(cmd: dict):
    """Cập nhật STATE theo một command JSON: {target, action, reason}."""
    global last_reason
    target = cmd.get("target")
    action = cmd.get("action")
    last_reason = cmd.get("reason", last_reason)

    if target == "board":
        # board: action chính là nhãn hiển thị (Good/Moderate/Unhealthy/Very Unhealthy)
        STATE["board"] = action
    elif target in ("fan", "purifier", "mist"):
        STATE[target] = action  # on / off / max
    else:
        print(f"[{DEVICE_ID}] command không hợp lệ: {cmd}", flush=True)
        return False
    return True


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[{DEVICE_ID}] connected rc={rc}, subscribe {CMD_TOPIC}", flush=True)
    client.subscribe(CMD_TOPIC, qos=1)
    publish_status(client)  # công bố trạng thái ban đầu


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    print(f"[{DEVICE_ID}] disconnected rc={rc}, sẽ tự reconnect...", flush=True)


def on_message(client, userdata, msg):
    try:
        cmd = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        print(f"[{DEVICE_ID}] payload không phải JSON: {msg.payload!r}", flush=True)
        return
    print(f"[{DEVICE_ID}] <- {msg.topic} {cmd}", flush=True)
    if apply_command(cmd):
        publish_status(client)


def main():
    client = mqtt.Client(client_id=DEVICE_ID)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[{DEVICE_ID}] broker chưa sẵn sàng ({exc}), thử lại 2s", flush=True)
            time.sleep(2)

    running = {"flag": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(flag=False))
    signal.signal(signal.SIGINT, lambda *_: running.update(flag=False))

    client.loop_start()
    while running["flag"]:
        time.sleep(1)
    client.loop_stop()
    client.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    main()
