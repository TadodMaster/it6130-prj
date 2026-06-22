"""Virtual air-quality sensor node.

Đọc cấu hình từ biến môi trường, mô phỏng nồng độ bụi/khí biến thiên theo thời gian
trong ngày (có xu hướng, không random độc lập), thỉnh thoảng sinh tình huống ô nhiễm
đột biến, rồi publish JSON telemetry lên MQTT.
"""
import json
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# 1. Đọc cấu hình từ env (yêu cầu 4.9)
# ---------------------------------------------------------------------------
CITY_ID = os.getenv("CITY_ID", "hanoi")
STATION_ID = os.getenv("STATION_ID", "station-01")
DEVICE_ID = os.getenv("DEVICE_ID", f"sensor-{STATION_ID}")
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
PUBLISH_INTERVAL = int(os.getenv("PUBLISH_INTERVAL", "5"))

TOPIC = f"city/{STATION_ID}/sensor/telemetry"

# Mỗi trạm có một mức nền (baseline) khác nhau để dashboard phân biệt được.
STATION_BASE = {
    "station-01": {"pm2_5": 30, "pm10": 55, "co": 1.0, "no2": 30, "o3": 40},
    "station-02": {"pm2_5": 18, "pm10": 38, "co": 0.6, "no2": 20, "o3": 55},
    "station-03": {"pm2_5": 50, "pm10": 85, "co": 1.4, "no2": 45, "o3": 35},
}
BASE = STATION_BASE.get(STATION_ID, STATION_BASE["station-01"])


def now_iso() -> str:
    """Trả về timestamp ISO-8601 UTC, ví dụ 2026-06-22T10:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def diurnal_factor() -> float:
    """Hệ số theo giờ trong ngày: cao điểm giao thông sáng (~8h) và chiều (~18h)."""
    hour = datetime.now(timezone.utc).hour
    morning = math.exp(-((hour - 8) ** 2) / 5.0)
    evening = math.exp(-((hour - 18) ** 2) / 5.0)
    return 1.0 + 0.7 * (morning + evening)


# ---------------------------------------------------------------------------
# 2. Trạng thái mô phỏng (giữ giá trị trước để tạo xu hướng - random walk)
# ---------------------------------------------------------------------------
state = {
    "pm2_5": BASE["pm2_5"],
    "pm10": BASE["pm10"],
    "co": BASE["co"],
    "no2": BASE["no2"],
    "o3": BASE["o3"],
}
# Đếm vòng lặp để chủ động sinh tình huống đột biến.
tick = 0
spike_remaining = 0  # số vòng còn lại của một đợt đột biến đang diễn ra


def step_toward(current: float, target: float, jitter: float) -> float:
    """Di chuyển dần current về target + nhiễu nhỏ -> tạo đường cong mượt có xu hướng."""
    nxt = current + (target - current) * 0.3 + random.uniform(-jitter, jitter)
    return max(0.0, nxt)


def simulate() -> dict:
    """Sinh một mẫu đo mới dựa trên baseline, nhịp ngày, và tình huống đột biến."""
    global tick, spike_remaining
    tick += 1
    f = diurnal_factor()

    # Cứ ~40 vòng thì kích hoạt một đợt ô nhiễm đột biến kéo dài vài vòng.
    if spike_remaining == 0 and tick % 40 == 0:
        spike_remaining = random.randint(4, 8)
    spike = spike_remaining > 0
    if spike:
        spike_remaining -= 1

    pm_mult = 3.2 if spike else 1.0          # bụi mịn tăng vọt khi đột biến
    co_mult = 9.0 / BASE["co"] if spike else 1.0  # đẩy CO vượt ngưỡng 9 ppm

    state["pm2_5"] = step_toward(state["pm2_5"], BASE["pm2_5"] * f * pm_mult, 4)
    state["pm10"] = step_toward(state["pm10"], BASE["pm10"] * f * pm_mult, 6)
    state["co"] = step_toward(state["co"], BASE["co"] * f * (co_mult if spike else 1.0), 0.2)
    state["no2"] = step_toward(state["no2"], BASE["no2"] * f, 5)
    state["o3"] = step_toward(state["o3"], BASE["o3"] * (2 - f * 0.5), 4)  # O3 ngược pha giao thông

    return {
        "device_id": DEVICE_ID,
        "city_id": CITY_ID,
        "station_id": STATION_ID,
        "pm2_5": round(state["pm2_5"], 1),
        "pm10": round(state["pm10"], 1),
        "co_ppm": round(state["co"], 2),
        "no2_ppb": round(state["no2"], 1),
        "o3_ppb": round(state["o3"], 1),
        "temperature": round(28 + 5 * math.sin(tick / 20) + random.uniform(-0.5, 0.5), 1),
        "humidity": round(65 + 10 * math.cos(tick / 25) + random.uniform(-1, 1), 1),
        "timestamp": now_iso(),
    }


# ---------------------------------------------------------------------------
# 3. MQTT client (có cơ chế reconnect tự động - yêu cầu nâng cao #8)
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[{DEVICE_ID}] connected to MQTT {MQTT_BROKER}:{MQTT_PORT}", flush=True)
    else:
        print(f"[{DEVICE_ID}] connect failed rc={rc}", flush=True)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    print(f"[{DEVICE_ID}] disconnected rc={rc}, paho sẽ tự reconnect...", flush=True)


def main():
    client = mqtt.Client(client_id=DEVICE_ID, protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # Thử kết nối lại cho tới khi broker sẵn sàng (lúc khởi động cùng compose).
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[{DEVICE_ID}] broker chưa sẵn sàng ({exc}), thử lại sau 2s", flush=True)
            time.sleep(2)

    client.loop_start()

    # Cho phép dừng container sạch sẽ (Ctrl+C / docker stop).
    running = {"flag": True}

    def shutdown(*_):
        running["flag"] = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while running["flag"]:
        payload = simulate()
        client.publish(TOPIC, json.dumps(payload), qos=1)
        print(f"[{DEVICE_ID}] -> {TOPIC} pm2_5={payload['pm2_5']} co={payload['co_ppm']}", flush=True)
        time.sleep(PUBLISH_INTERVAL)

    client.loop_stop()
    client.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    main()
