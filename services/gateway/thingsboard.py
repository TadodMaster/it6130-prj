"""Tích hợp ThingsBoard Cloud theo Gateway API (yêu cầu 4.10).

- Uplink: publish telemetry nhiều trạm kèm AQI lên topic v1/gateway/telemetry.
- Downlink (RPC): subscribe v1/gateway/rpc, nhận lệnh setFan/setPurifier... và trả reply.

Bật/tắt qua biến môi trường TB_ENABLED. Nếu false, mọi hàm trở thành no-op để hệ
thống local vẫn chạy bình thường mà không cần tài khoản ThingsBoard.

Module dạng thủ tục (không OOP): gọi init(on_rpc) một lần lúc khởi động gateway.
"""
import json
import os

import paho.mqtt.client as mqtt

ENABLED = os.getenv("TB_ENABLED", "false").lower() == "true"
HOST = os.getenv("TB_HOST", "thingsboard.cloud")
PORT = int(os.getenv("TB_PORT", "1883"))
TOKEN = os.getenv("TB_GATEWAY_TOKEN", "")

_client = None
_on_rpc = None  # callback(station_id, method, params) -> dict reply


def _handle_connect(client, userdata, flags, rc, properties=None):
    print(f"[gateway] ThingsBoard connect rc={rc}", flush=True)
    client.subscribe("v1/gateway/rpc", qos=1)  # nhận RPC điều khiển từ trung tâm


def _handle_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return
    # data: {"device":"station-01","data":{"id":9,"method":"setPurifier","params":true}}
    device = data.get("device")
    body = data.get("data", {})
    method = body.get("method")
    params = body.get("params")
    req_id = body.get("id")
    print(f"[gateway] RPC <- {device} {method}({params})", flush=True)

    result = {"success": False}
    if _on_rpc:
        try:
            result = _on_rpc(device, method, params) or {"success": True}
        except Exception as exc:  # noqa: BLE001
            result = {"success": False, "error": str(exc)}

    reply = {"device": device, "id": req_id, "data": result}
    client.publish("v1/gateway/rpc", json.dumps(reply), qos=1)


def init(on_rpc=None):
    """Kết nối ThingsBoard. on_rpc: callback(station_id, method, params) -> dict."""
    global _client, _on_rpc
    _on_rpc = on_rpc
    if not ENABLED:
        print("[gateway] ThingsBoard DISABLED (TB_ENABLED=false)", flush=True)
        return
    _client = mqtt.Client(protocol=mqtt.MQTTv311)
    _client.username_pw_set(TOKEN)  # device token = username
    _client.on_connect = _handle_connect
    _client.on_message = _handle_message
    _client.reconnect_delay_set(min_delay=1, max_delay=60)
    try:
        _client.connect(HOST, PORT, keepalive=60)
        _client.loop_start()
    except Exception as exc:  # noqa: BLE001
        print(f"[gateway] TB connect lỗi: {exc}", flush=True)


def connect_device(station_id: str):
    """Báo cho ThingsBoard biết một thiết bị con đã online dưới gateway."""
    if not ENABLED or not _client:
        return
    _client.publish("v1/gateway/connect",
                    json.dumps({"device": station_id}), qos=1)


def send_telemetry(station_id: str, values: dict, ts_ms: int):
    """Đẩy telemetry kèm AQI lên ThingsBoard theo Gateway API."""
    if not ENABLED or not _client:
        return
    payload = {station_id: [{"ts": ts_ms, "values": values}]}
    _client.publish("v1/gateway/telemetry", json.dumps(payload), qos=1)


def close():
    if _client:
        _client.loop_stop()
        _client.disconnect()
