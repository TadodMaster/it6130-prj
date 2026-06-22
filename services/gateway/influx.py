"""Ghi telemetry/AQI, event và trạng thái actuator vào InfluxDB v2.

Schema (yêu cầu 4.11):
  - air_quality   : tag city_id, station_id; field pm2_5, pm10, co_ppm, no2_ppb,
                    o3_ppb, aqi, temperature, humidity
  - gateway_events: tag station_id, event_type, severity, dominant;
                    field aqi, value, threshold
  - actuator_status: tag station_id; field fan, purifier, mist, board

Module dạng thủ tục (không OOP): gọi init() một lần, rồi dùng các hàm write_*.
"""
import os

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
TOKEN = os.getenv("INFLUXDB_TOKEN", "super-secret-admin-token")
ORG = os.getenv("INFLUXDB_ORG", "air")
BUCKET = os.getenv("INFLUXDB_BUCKET", "air_quality")

_client = None
_write_api = None


def init():
    """Kết nối InfluxDB (gọi một lần lúc khởi động gateway)."""
    global _client, _write_api
    try:
        _client = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
        _write_api = _client.write_api(write_options=SYNCHRONOUS)
        print(f"[gateway] InfluxDB connected: {URL}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[gateway] InfluxDB connect lỗi: {exc}", flush=True)


def _write(point: Point):
    if _write_api is None:
        init()
    try:
        _write_api.write(bucket=BUCKET, org=ORG, record=point)
    except Exception as exc:  # noqa: BLE001
        print(f"[gateway] InfluxDB write lỗi: {exc}", flush=True)


def write_air_quality(m: dict, aqi: dict):
    _write(
        Point("air_quality")
        .tag("city_id", m.get("city_id", "unknown"))
        .tag("station_id", m["station_id"])
        .field("pm2_5", float(m.get("pm2_5", 0)))
        .field("pm10", float(m.get("pm10", 0)))
        .field("co_ppm", float(m.get("co_ppm", 0)))
        .field("no2_ppb", float(m.get("no2_ppb", 0)))
        .field("o3_ppb", float(m.get("o3_ppb", 0)))
        .field("temperature", float(m.get("temperature", 0)))
        .field("humidity", float(m.get("humidity", 0)))
        .field("aqi", int(aqi["aqi"]))
    )


def write_event(station_id: str, ev: dict):
    _write(
        Point("gateway_events")
        .tag("station_id", station_id)
        .tag("event_type", ev["event_type"])
        .tag("severity", ev["severity"])
        .tag("dominant", str(ev.get("dominant")))
        .field("aqi", int(ev.get("aqi", 0)))
        .field("value", float(ev.get("value") or 0))
        .field("threshold", float(ev.get("threshold") or 0))
        .field("action_taken", str(ev.get("action_taken", "")))
    )


def write_actuator_status(status: dict):
    _write(
        Point("actuator_status")
        .tag("station_id", status["station_id"])
        .field("fan", str(status.get("fan")))
        .field("purifier", str(status.get("purifier")))
        .field("mist", str(status.get("mist")))
        .field("board", str(status.get("board")))
    )


def close():
    if _client:
        _client.close()
