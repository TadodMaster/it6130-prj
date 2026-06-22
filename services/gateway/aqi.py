"""Tính chỉ số AQI theo bảng breakpoint US EPA (nội suy tuyến tính).

AQI tổng của trạm = max các AQI thành phần; chất cho giá trị lớn nhất là 'dominant'.
"""
from typing import Optional

# Mỗi breakpoint: (C_lo, C_hi, I_lo, I_hi)
# Nguồn: US EPA Technical Assistance Document for the Reporting of Daily AQI.
BREAKPOINTS = {
    # PM2.5 (µg/m3, trung bình 24h)
    "pm2_5": [
        (0.0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ],
    # PM10 (µg/m3, 24h)
    "pm10": [
        (0, 54, 0, 50),
        (55, 154, 51, 100),
        (155, 254, 101, 150),
        (255, 354, 151, 200),
        (355, 424, 201, 300),
        (425, 504, 301, 400),
        (505, 604, 401, 500),
    ],
    # CO (ppm, 8h)
    "co_ppm": [
        (0.0, 4.4, 0, 50),
        (4.5, 9.4, 51, 100),
        (9.5, 12.4, 101, 150),
        (12.5, 15.4, 151, 200),
        (15.5, 30.4, 201, 300),
        (30.5, 40.4, 301, 400),
        (40.5, 50.4, 401, 500),
    ],
    # NO2 (ppb, 1h)
    "no2_ppb": [
        (0, 53, 0, 50),
        (54, 100, 51, 100),
        (101, 360, 101, 150),
        (361, 649, 151, 200),
        (650, 1249, 201, 300),
        (1250, 1649, 301, 400),
        (1650, 2049, 401, 500),
    ],
    # O3 (ppb, 8h) - chỉ dùng tới ~200, đủ cho mô phỏng
    "o3_ppb": [
        (0, 54, 0, 50),
        (55, 70, 51, 100),
        (71, 85, 101, 150),
        (86, 105, 151, 200),
        (106, 200, 201, 300),
    ],
}


def aqi_for(pollutant: str, conc: float) -> Optional[float]:
    """AQI thành phần cho một chất tại nồng độ conc. None nếu vượt bảng / không hỗ trợ."""
    table = BREAKPOINTS.get(pollutant)
    if table is None or conc is None:
        return None
    conc = max(0.0, float(conc))
    for c_lo, c_hi, i_lo, i_hi in table:
        if c_lo <= conc <= c_hi:
            return (i_hi - i_lo) / (c_hi - c_lo) * (conc - c_lo) + i_lo
    # Vượt giá trị cao nhất của bảng -> kẹp ở mức trần.
    return float(table[-1][3])


def category(aqi: float) -> str:
    """Phân cấp AQI thành nhãn chữ."""
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def board_label(aqi: float) -> str:
    """Nhãn ngắn để hiển thị trên bảng cảnh báo của trạm."""
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "USG"
    if aqi <= 200:
        return "Unhealthy"
    return "Very Unhealthy"


def compute_aqi(measurement: dict) -> dict:
    """Tính AQI tổng + chất dominant từ một bản đo.

    Trả về dict: {aqi, dominant, category, board, components}
    """
    components = {}
    for pollutant in ("pm2_5", "pm10", "co_ppm", "no2_ppb", "o3_ppb"):
        value = measurement.get(pollutant)
        sub = aqi_for(pollutant, value)
        if sub is not None:
            components[pollutant] = round(sub)

    if not components:
        return {"aqi": 0, "dominant": None, "category": "Good",
                "board": "Good", "components": {}}

    dominant = max(components, key=components.get)
    aqi = components[dominant]
    return {
        "aqi": aqi,
        "dominant": dominant,
        "category": category(aqi),
        "board": board_label(aqi),
        "components": components,
    }
