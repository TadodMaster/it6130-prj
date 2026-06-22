"""REST API (FastAPI) cho Virtual Air Quality Gateway.

Theo dõi trạng thái mới nhất từng trạm + event gần đây bằng cách subscribe MQTT,
và cho phép gửi lệnh điều khiển thủ công bằng cách publish command.

Endpoints (yêu cầu 4.9):
  GET  /health
  GET  /stations
  GET  /stations/{station_id}/state
  GET  /stations/{station_id}/events
  POST /stations/{station_id}/command   body: {"target","action","reason"}
"""
import json
import os
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Bộ nhớ trạng thái (cập nhật realtime từ MQTT).
STATE = defaultdict(dict)                       # station_id -> {normalized, actuator}
EVENTS = defaultdict(lambda: deque(maxlen=50))  # station_id -> deque[event]
mqtt_client: mqtt.Client | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# MQTT background client
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[air-api] MQTT connected rc={rc}", flush=True)
    client.subscribe([
        ("city/+/gateway/normalized", 1),
        ("city/+/gateway/event", 1),
        ("city/+/actuator/status", 1),
    ])


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return
    station = data.get("station_id")
    if not station:
        return
    if msg.topic.endswith("/gateway/normalized"):
        STATE[station]["normalized"] = data
    elif msg.topic.endswith("/actuator/status"):
        STATE[station]["actuator"] = data
    elif msg.topic.endswith("/gateway/event"):
        EVENTS[station].appendleft(data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_client
    mqtt_client = mqtt.Client(client_id="air-api", protocol=mqtt.MQTTv311)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as exc:  # noqa: BLE001
        print(f"[air-api] MQTT connect lỗi: {exc}", flush=True)
    mqtt_client.loop_start()
    yield
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(title="Virtual Air Quality Gateway API", version="1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Command(BaseModel):
    target: str   # fan | purifier | mist | board
    action: str   # on | off | max | <board label>
    reason: str = "manual"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    connected = bool(mqtt_client and mqtt_client.is_connected())
    return {"status": "ok" if connected else "degraded",
            "mqtt_connected": connected,
            "stations_known": list(STATE.keys()),
            "timestamp": now_iso()}


@app.get("/stations")
def list_stations():
    out = []
    for sid, data in STATE.items():
        norm = data.get("normalized", {})
        out.append({
            "station_id": sid,
            "aqi": norm.get("aqi"),
            "dominant": norm.get("dominant"),
            "category": norm.get("category"),
        })
    return {"count": len(out), "stations": out}


@app.get("/stations/{station_id}/state")
def station_state(station_id: str):
    if station_id not in STATE:
        raise HTTPException(404, f"Chưa có dữ liệu cho {station_id}")
    return STATE[station_id]


@app.get("/stations/{station_id}/events")
def station_events(station_id: str, limit: int = 20):
    return {"station_id": station_id,
            "events": list(EVENTS[station_id])[:limit]}


@app.post("/stations/{station_id}/command")
def send_command(station_id: str, cmd: Command):
    if not (mqtt_client and mqtt_client.is_connected()):
        raise HTTPException(503, "MQTT chưa kết nối")
    payload = {"station_id": station_id, "target": cmd.target,
               "action": cmd.action, "reason": cmd.reason, "timestamp": now_iso()}
    mqtt_client.publish(f"city/{station_id}/actuator/command",
                        json.dumps(payload), qos=1)
    return {"published": True, "topic": f"city/{station_id}/actuator/command",
            "payload": payload}
