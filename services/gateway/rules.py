"""Rule engine: từ AQI + nồng độ -> sinh command điều khiển actuator và event cảnh báo.

Tối thiểu 4 luật theo cấp AQI (yêu cầu 4.9).
"""
from typing import List, Tuple

# Ngưỡng có thể chỉnh từ ngoài (Shared Attributes/ThingsBoard - nâng cao #3).
THRESHOLDS = {
    "aqi_unhealthy": 150,
    "aqi_very_unhealthy": 200,
    "co_high_ppm": 9.0,
    "aqi_good": 50,
}


def evaluate(measurement: dict, aqi_result: dict) -> Tuple[List[dict], List[dict]]:
    """Đánh giá luật.

    Trả về (commands, events):
      - commands: [{target, action, reason}]  -> gateway publish tới actuator
      - events:   [{event_type, severity, aqi, dominant, value, threshold, action_taken}]
    """
    aqi = aqi_result["aqi"]
    dominant = aqi_result["dominant"]
    co = measurement.get("co_ppm", 0.0) or 0.0

    commands: List[dict] = []
    events: List[dict] = []
    actions: List[str] = []

    def cmd(target, action, reason):
        commands.append({"target": target, "action": action, "reason": reason})
        actions.append(f"{target}_{action}")

    # --- Luật 1: AQI > 150 (Unhealthy) ---
    if aqi > THRESHOLDS["aqi_unhealthy"]:
        cmd("purifier", "on", "aqi_unhealthy")
        cmd("fan", "on", "aqi_unhealthy")
        cmd("board", "Unhealthy", "aqi_unhealthy")
        events.append({
            "event_type": "aqi_unhealthy", "severity": "warning",
            "aqi": aqi, "dominant": dominant,
            "value": measurement.get(dominant), "threshold": THRESHOLDS["aqi_unhealthy"],
        })

    # --- Luật 2: AQI > 200 (Very Unhealthy) ---
    if aqi > THRESHOLDS["aqi_very_unhealthy"]:
        cmd("mist", "on", "aqi_very_unhealthy")
        cmd("board", "Very Unhealthy", "aqi_very_unhealthy")
        events.append({
            "event_type": "aqi_very_unhealthy", "severity": "critical",
            "aqi": aqi, "dominant": dominant,
            "value": measurement.get(dominant), "threshold": THRESHOLDS["aqi_very_unhealthy"],
        })

    # --- Luật 3: CO > 9 ppm (nguy hiểm trực tiếp) ---
    if co > THRESHOLDS["co_high_ppm"]:
        cmd("fan", "max", "co_high")
        events.append({
            "event_type": "co_high", "severity": "critical",
            "aqi": aqi, "dominant": "co_ppm",
            "value": co, "threshold": THRESHOLDS["co_high_ppm"],
        })

    # --- Luật 4: AQI <= 50 (Good) -> tắt thiết bị ---
    if aqi <= THRESHOLDS["aqi_good"]:
        cmd("fan", "off", "aqi_good")
        cmd("purifier", "off", "aqi_good")
        cmd("mist", "off", "aqi_good")
        cmd("board", "Good", "aqi_good")
        events.append({
            "event_type": "aqi_good", "severity": "info",
            "aqi": aqi, "dominant": dominant,
            "value": measurement.get(dominant), "threshold": THRESHOLDS["aqi_good"],
        })

    # Gắn chuỗi action_taken vào mỗi event để ghi log/dashboard.
    action_str = ",".join(actions) if actions else "none"
    for ev in events:
        ev["action_taken"] = action_str

    return commands, events
