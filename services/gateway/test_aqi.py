"""Unit test cho hàm tính AQI và rule engine (chạy: pytest gateway/).

Yêu cầu nâng cao #7. Không cần MQTT/InfluxDB.
"""
from aqi import aqi_for, board_label, compute_aqi
from rules import evaluate


def test_pm25_breakpoint_endpoints():
    # 12.0 µg/m3 -> đúng cận trên cấp Good (AQI 50)
    assert round(aqi_for("pm2_5", 12.0)) == 50
    # 35.4 -> cận trên Moderate (AQI 100)
    assert round(aqi_for("pm2_5", 35.4)) == 100


def test_pm25_interpolation_midpoint():
    # 9.0 nằm trong [0,12]->[0,50]: 9/12*50 = 37.5 -> 38
    assert round(aqi_for("pm2_5", 9.0)) == 38


def test_dominant_is_max_component():
    m = {"pm2_5": 165.0, "pm10": 60.0, "co_ppm": 1.0}
    res = compute_aqi(m)
    assert res["dominant"] == "pm2_5"
    assert res["aqi"] > 150
    assert res["board"] == "Unhealthy"


def test_board_labels():
    assert board_label(40) == "Good"
    assert board_label(120) == "USG"
    assert board_label(180) == "Unhealthy"
    assert board_label(250) == "Very Unhealthy"


def test_rule_unhealthy_turns_on_purifier_and_fan():
    m = {"pm2_5": 165.0, "pm10": 210.0, "co_ppm": 4.5}
    aqi = compute_aqi(m)
    commands, events = evaluate(m, aqi)
    targets = {(c["target"], c["action"]) for c in commands}
    assert ("purifier", "on") in targets
    assert ("fan", "on") in targets
    assert any(e["event_type"] == "aqi_unhealthy" for e in events)


def test_rule_co_high_sets_fan_max():
    m = {"pm2_5": 10.0, "pm10": 20.0, "co_ppm": 12.0}
    aqi = compute_aqi(m)
    commands, events = evaluate(m, aqi)
    assert ("fan", "max") in {(c["target"], c["action"]) for c in commands}
    assert any(e["event_type"] == "co_high" and e["severity"] == "critical" for e in events)


def test_rule_good_turns_off():
    m = {"pm2_5": 5.0, "pm10": 10.0, "co_ppm": 0.5}
    aqi = compute_aqi(m)
    commands, _ = evaluate(m, aqi)
    assert ("fan", "off") in {(c["target"], c["action"]) for c in commands}
