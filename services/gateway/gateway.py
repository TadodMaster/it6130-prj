"""Edge IoT gateway.

- Subscribe telemetry tất cả trạm, validate + normalize.
- Tính AQI và xác định chất dominant.
- Lưu trạng thái mới nhất từng trạm; ghi telemetry + AQI + event + status vào InfluxDB.
- Chạy rule engine: publish event và gửi command tới actuator.
- Publish dữ liệu normalized; đẩy telemetry (kèm AQI) lên ThingsBoard và nhận RPC.
"""
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import influx
import thingsboard as tb
from aqi import compute_aqi
from rules import evaluate

CITY_ID = os.getenv("CITY_ID", "hanoi")
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TELEMETRY_SUB = "city/+/sensor/telemetry"
STATUS_SUB = "city/+/actuator/status"

REQUIRED_FIELDS = ("station_id", "pm2_5", "pm10")

# Trạng thái mới nhất từng trạm (dùng cho normalized + REST API gián tiếp).
LATEST = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_normalize(m: dict):
    """Kiểm tra trường bắt buộc, ép kiểu số, kẹp giá trị âm về 0."""
    for f in REQUIRED_FIELDS:
        if f not in m:
            print(f"[gateway] bỏ qua bản ghi thiếu '{f}': {m}", flush=True)
            return None
    out = dict(m)
    for f in ("pm2_5", "pm10", "co_ppm", "no2_ppb", "o3_ppb", "temperature", "humidity"):
        try:
            out[f] = max(0.0, float(m.get(f, 0)))
        except (TypeError, ValueError):
            out[f] = 0.0
    return out


def _log(label: str, obj: dict):
    print(f"[gateway] {label}:\n{json.dumps(obj, ensure_ascii=False, indent=2)}",
          flush=True)


def handle_telemetry(client, m: dict):
    station = m["station_id"]
    aqi = compute_aqi(m)

    # 1. Lưu trạng thái mới nhất.
    LATEST[station] = {"measurement": m, "aqi": aqi, "updated_at": now_iso()}

    # Log full telemetry vừa nhận.
    _log(f"TELEMETRY {station}", m)

    # 2. Ghi InfluxDB.
    influx.write_air_quality(m, aqi)

    # 3. Publish normalized (telemetry + AQI đã tính).
    normalized = {**m, "aqi": aqi["aqi"], "dominant": aqi["dominant"],
                  "category": aqi["category"]}
    client.publish(f"city/{station}/gateway/normalized",
                   json.dumps(normalized), qos=1)
    _log(f"NORMALIZED {station}", normalized)

    # 4. Rule engine -> command tới actuator + event.
    commands, events = evaluate(m, aqi)
    for cmd in commands:
        payload = {"station_id": station, **cmd, "timestamp": now_iso()}
        client.publish(f"city/{station}/actuator/command",
                       json.dumps(payload), qos=1)
        _log(f"COMMAND {station} -> actuator", payload)

    for ev in events:
        ev_full = {"station_id": station, **ev, "timestamp": now_iso()}
        client.publish(f"city/{station}/gateway/event",
                       json.dumps(ev_full), qos=1)
        influx.write_event(station, ev_full)
        _log(f"EVENT {station}", ev_full)

    # 5. Đẩy lên ThingsBoard (kèm AQI). No-op nếu TB_ENABLED=false.
    tb_payload = {
        "pm2_5": m["pm2_5"], "pm10": m["pm10"], "co_ppm": m.get("co_ppm"),
        "no2_ppb": m.get("no2_ppb"), "o3_ppb": m.get("o3_ppb"),
        "aqi": aqi["aqi"], "dominant": aqi["dominant"],
        "temperature": m.get("temperature"), "humidity": m.get("humidity"),
    }
    tb.send_telemetry(station, tb_payload, ts_ms=int(time.time() * 1000))

    # Summary line + full AQI block.
    print(f"[gateway] {station}: AQI={aqi['aqi']} ({aqi['category']}) "
          f"dominant={aqi['dominant']}", flush=True)

# def handle_telemetry(client, m: dict):
#     station = m["station_id"]
#     aqi = compute_aqi(m)

#     # 1. Lưu trạng thái mới nhất.
#     LATEST[station] = {"measurement": m, "aqi": aqi, "updated_at": now_iso()}

#     # 2. Ghi InfluxDB.
#     influx.write_air_quality(m, aqi)

#     # 3. Publish normalized (telemetry + AQI đã tính).
#     normalized = {**m, "aqi": aqi["aqi"], "dominant": aqi["dominant"],
#                   "category": aqi["category"]}
#     client.publish(f"city/{station}/gateway/normalized",
#                    json.dumps(normalized), qos=1)

#     # 4. Rule engine -> command tới actuator + event.
#     commands, events = evaluate(m, aqi)
#     for cmd in commands:
#         payload = {"station_id": station, **cmd, "timestamp": now_iso()}
#         client.publish(f"city/{station}/actuator/command",
#                        json.dumps(payload), qos=1)

#     for ev in events:
#         ev_full = {"station_id": station, **ev, "timestamp": now_iso()}
#         client.publish(f"city/{station}/gateway/event",
#                        json.dumps(ev_full), qos=1)
#         influx.write_event(station, ev_full)
#         print(f"[gateway] EVENT {station}: {ev['event_type']} "
#               f"(aqi={aqi['aqi']}, sev={ev['severity']})", flush=True)

#     # 5. Đẩy lên ThingsBoard (kèm AQI). No-op nếu TB_ENABLED=false.
#     tb.send_telemetry(station, {
#         "pm2_5": m["pm2_5"], "pm10": m["pm10"], "co_ppm": m.get("co_ppm"),
#         "no2_ppb": m.get("no2_ppb"), "o3_ppb": m.get("o3_ppb"),
#         "aqi": aqi["aqi"], "dominant": aqi["dominant"],
#         "temperature": m.get("temperature"), "humidity": m.get("humidity"),
#     }, ts_ms=int(time.time() * 1000))

#     print(f"[gateway] {station}: AQI={aqi['aqi']} ({aqi['category']}) "
#           f"dominant={aqi['dominant']}", flush=True)


# def handle_status(status: dict):
#     """Lưu trạng thái actuator vào Influx + cache, và đẩy lên ThingsBoard."""
#     station = status.get("station_id")
#     if not station:
#         return

#     prev = LATEST.get(station, {}).get("actuator", {})
#     LATEST.setdefault(station, {})["actuator"] = status
#     influx.write_actuator_status(status)

#     # Đẩy trạng thái actuator lên ThingsBoard để widget phản ánh cả khi rule
#     # engine TỰ đổi trạng thái (không chỉ khi người dùng bấm nút). Chỉ gửi khi
#     # có thay đổi thật để tránh spam telemetry mỗi chu kỳ sensor.
#     fields = ("fan", "purifier", "mist", "board")
#     changed = [f for f in fields if status.get(f) != prev.get(f)]
#     print(f"[gateway] STATUS <- {station} "
#           f"fan={status.get('fan')} purifier={status.get('purifier')} "
#           f"mist={status.get('mist')} board={status.get('board')} "
#           f"| changed={','.join(changed) if changed else 'none'}", flush=True)

#     if changed:
#         vals = {f: status.get(f) for f in fields}
#         tb.send_telemetry(station, vals, ts_ms=int(time.time() * 1000))
#         print(f"[gateway] -> TB telemetry {station}: {vals}", flush=True)

def handle_status(status: dict):
    station = status.get("station_id")
    if not station:
        return
    
    LATEST.setdefault(station, {})["actuator"] = status
    influx.write_actuator_status(status)
    # cập nhật lên ThingsBoard
    tb.send_telemetry(
        station,
        {
            "fan": status.get("fan") != "off",
            "purifier": status.get("purifier") == "on",
            "mist": status.get("mist") == "on",
            "board": status.get("board"),
        },
        ts_ms=int(time.time() * 1000)
    )


# ---------------------------------------------------------------------------
# RPC từ ThingsBoard -> chuyển thành command MQTT tới actuator
# ---------------------------------------------------------------------------
# def make_rpc_handler(client):
#     set_map = {
#         "setFan": "fan", "setPurifier": "purifier",
#         "setMist": "mist", "setBoard": "board",
#     }
#     # get-method -> target. "getValue" giữ tương thích với switch đã cấu hình.
#     get_map = {
#         "getValue": "purifier",
#         "getFan": "fan", "getPurifier": "purifier",
#         "getMist": "mist", "getBoard": "board",
#     }

#     def on_rpc(device, method, params):
#         # --- GET: trả trạng thái hiện tại để widget hiển thị đúng lúc load ---
#         if method in get_map:
#             target = get_map[method]
#             state = LATEST.get(device, {}).get("actuator", {}).get(target, "off")
#             result = state if target == "board" else state in ("on", "max")
#             print(f"[gateway] RPC GET  {method} {device}.{target} "
#                   f"state={state!r} -> {result!r}", flush=True)
#             return result

#         # --- SET: chuyển RPC thành command MQTT tới actuator ---
#         target = set_map.get(method)
#         if not target:
#             print(f"[gateway] RPC UNKNOWN method={method!r} device={device}", flush=True)
#             return {"success": False, "error": f"unknown method {method}"}
#         if target == "board":
#             action = str(params)
#         else:
#             action = "on" if params in (True, "on", 1) else "off"
#         payload = {"station_id": device, "target": target,
#                    "action": action, "reason": "manual_rpc", "timestamp": now_iso()}
#         client.publish(f"city/{device}/actuator/command", json.dumps(payload), qos=1)
#         print(f"[gateway] RPC SET  {method} {device}.{target} params={params!r} "
#               f"-> action={action} (command published)", flush=True)
#         return {"success": True, "target": target, "action": action}
#     return on_rpc

def make_rpc_handler(client):
    method_map = {
        "setFan": "fan", "setPurifier": "purifier",
        "setMist": "mist", "setBoard": "board",
    }
    def on_rpc(device, method, params):
        target = method_map.get(method)
        if not target:
            return {"success": False, "error": f"unknown method {method}"}
        if target == "board":
            action = str(params)
        else:
            action = "on" if params in (True, "on", 1) else "off"
        payload = {"station_id": device, "target": target, "action": action, "reason": "manual_rpc", "timestamp": now_iso()}
        client.publish(f"city/{device}/actuator/command", json.dumps(payload), qos=1)
        return {"success": True, "target": target, "action": action}
    return on_rpc


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[gateway] connected rc={rc}", flush=True)
    client.subscribe([(TELEMETRY_SUB, 1), (STATUS_SUB, 1)])


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        print(f"{msg.topic}: {data}")
    except json.JSONDecodeError:
        print(f"[gateway] payload không phải JSON trên {msg.topic}", flush=True)
        return

    if msg.topic.endswith("/sensor/telemetry"):
        m = validate_normalize(data)
        if m:
            handle_telemetry(client, m)
    elif msg.topic.endswith("/actuator/status"):
        handle_status(data)


def main():
    influx.init()

    client = mqtt.Client(client_id="air-gateway", protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[gateway] broker chưa sẵn sàng ({exc}), thử lại 2s", flush=True)
            time.sleep(2)

    tb.init(on_rpc=make_rpc_handler(client))
    for st in ("station-01", "station-02", "station-03"):
        tb.connect_device(st)

    running = {"flag": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(flag=False))
    signal.signal(signal.SIGINT, lambda *_: running.update(flag=False))

    client.loop_start()
    while running["flag"]:
        time.sleep(1)
    client.loop_stop()
    client.disconnect()
    tb.close()
    influx.close()
    sys.exit(0)


if __name__ == "__main__":
    main()