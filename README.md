# Virtual Smart Air Quality Gateway (Đề tài 4 - IT6130)
*GVHD: TS. Đặng Tuấn Linh – TS. Trần Hải Anh · Học phần IT6130 – Lập trình và ảo hóa cho IoT.*

Hệ thống **Virtual IoT Gateway** giám sát chất lượng không khí đô thị, ảo hóa hoàn toàn bằng Docker Compose (12 container, không cần phần cứng vật lý).

Nhiều **trạm cảm biến ảo** đo bụi mịn (PM2.5, PM10) và khí ô nhiễm (CO, NO₂, O₃) gửi telemetry qua MQTT. Một **edge gateway** ở biên chuẩn hóa dữ liệu, tính chỉ số **AQI**, chạy **rule engine** tự động điều khiển quạt thông gió / máy lọc khí / phun sương / bảng cảnh báo. Dữ liệu được lưu vào **InfluxDB**, trực quan hóa trên **Grafana**, đồng bộ hai chiều với **ThingsBoard Cloud** (telemetry + RPC), kèm **REST API** và **Web dashboard** để truy vấn và điều khiển thủ công.

> 📄 Báo cáo chi tiết: [`IT6130_-_Final_Report.pdf`](./docs/IT6130_-_Final_Report.pdf) · Đề bài: [`topic-4.pdf`](./docs/topic-4.pdf)

## Tính năng chính

- **Sensor có ý nghĩa**: dữ liệu biến thiên theo nhịp ngày (2 đỉnh cao điểm giao thông 8h/18h), xu hướng mượt (random walk) và tình huống ô nhiễm đột biến, thay vì số ngẫu nhiên rời rạc.
- **Edge computing**: tính AQI và điều khiển ngay tại gateway — độ trễ thấp, vẫn hoạt động khi mất kết nối cloud.
- **AQI theo chuẩn US EPA**: nội suy tuyến tính cho 5 chất, xác định *dominant pollutant*.
- **Rule engine động**: ngưỡng tách rời logic, có thể chỉnh từ xa qua ThingsBoard Shared Attributes.
- **Đồng bộ 2 chiều cloud**: uplink telemetry theo Gateway API + downlink RPC điều khiển thiết bị.
- **Triển khai 1 lệnh**: `docker compose up` với healthcheck, volume, mạng nội bộ.

## Kiến trúc

```
Virtual Sensors  ─┐                              ┌─ InfluxDB (time-series)
(station 01/02/03)│        ┌──────────────┐      │
                  ├─ MQTT ─┤ Edge Gateway ├──────┼─ Grafana (dashboard edge)
Virtual Actuators │ broker │ AQI + rules  │      │
(fan/purifier/...)┘(mosq.) │ TB gateway   │      └─ ThingsBoard Cloud (telemetry + RPC)
                           └──────┬───────┘
        Control Web ── air-api (FastAPI REST) ─┘
```

## Các service (12 container trên mạng `air-net`)

| Service               | Cổng | Mô tả                                        |
| --------------------- | ---- | -------------------------------------------- |
| `mosquitto`           | 1883 | MQTT broker trung tâm                        |
| `sensor-station-0X`   | —    | 3× virtual sensor, publish telemetry         |
| `actuator-station-0X` | —    | 3× virtual actuator, nhận command            |
| `air-gateway`         | —    | Edge gateway: AQI, rule engine, TB sync      |
| `influxdb`            | 8086 | CSDL time-series                             |
| `grafana`             | 3000 | Dashboard edge                               |
| `air-api`             | 8000 | REST API (FastAPI)                           |
| `control-web`         | 8080 | Web dashboard điều khiển thủ công            |

## Công nghệ

Python 3.10+ · MQTT (paho-mqtt) · Eclipse Mosquitto 2 · InfluxDB 2.7 · Grafana 11.3 · FastAPI + Uvicorn · ThingsBoard Cloud · Docker Compose.

## Thiết kế MQTT

Cây topic phân cấp theo `station_id` → thêm trạm mới chỉ cần đổi `station_id`, không sửa logic gateway (gateway subscribe theo wildcard `city/+/...`).

```
city/{station_id}/sensor/telemetry     # dữ liệu đo thô từ sensor
city/{station_id}/actuator/command     # lệnh tới fan / purifier / mist / board
city/{station_id}/actuator/status      # trạng thái actuator (retained)
city/{station_id}/gateway/normalized   # dữ liệu chuẩn hóa + AQI
city/{station_id}/gateway/event        # event cảnh báo do gateway sinh ra
```

Mọi bản tin dùng **JSON**, QoS 1; status của actuator bật cờ **retain**. Ví dụ telemetry:

```json
{
  "device_id": "sensor-station-01", "station_id": "station-01", "city_id": "hanoi",
  "pm2_5": 165.0, "pm10": 210.0, "co_ppm": 4.5, "no2_ppb": 80.0, "o3_ppb": 60.0,
  "temperature": 31.2, "humidity": 70.0, "timestamp": "2026-06-18T08:00:05Z"
}
```

## Rule engine

| Điều kiện                    | Hành động                              | Severity |
| ---------------------------- | -------------------------------------- | -------- |
| AQI > 150 (Unhealthy)        | Bật purifier + fan, board = Unhealthy  | warning  |
| AQI > 200 (Very Unhealthy)   | Bật thêm mist, board = Very Unhealthy  | critical |
| CO > 9 ppm                   | Bật fan mức max, event `co_high`       | critical |
| AQI ≤ 50 (Good)              | Tắt fan/purifier/mist, board = Good    | info     |

Phân cấp AQI theo US EPA: Good (0–50) · Moderate (51–100) · Unhealthy for Sensitive Groups (101–150) · Unhealthy (151–200) · Very Unhealthy (201–300) · Hazardous (>300).

## REST API

| Method + Endpoint                    | Chức năng                                   |
| ------------------------------------ | ------------------------------------------- |
| `GET  /health`                       | Trạng thái hệ thống + kết nối MQTT          |
| `GET  /stations`                     | Danh sách trạm kèm AQI, dominant, category  |
| `GET  /stations/{id}/state`          | Trạng thái hiện tại của một trạm            |
| `GET  /stations/{id}/events`         | Event gần đây của trạm                      |
| `POST /stations/{id}/command`        | Gửi lệnh điều khiển thủ công (publish MQTT) |

## Chạy hệ thống

```bash
cp .env.example .env   # chỉnh sửa nếu cần (bật/tắt ThingsBoard qua TB_ENABLED)
docker compose up -d --build
docker compose ps
docker compose logs -f air-gateway
```

## Cổng truy cập

| Service     | URL                          |
| ----------- | ---------------------------- |
| Control Web | <http://localhost:8080>      |
| Grafana     | <http://localhost:3000>      |
| InfluxDB    | <http://localhost:8086>      |
| FastAPI     | <http://localhost:8000/docs> |
| MQTT broker | localhost:1883               |

## Cấu trúc thư mục

```
it6130-prj/
├── docker-compose.yml
├── .env / .env.example
├── pyproject.toml
├── docs                                # Đề tài và báo cáo của nhóm
├── infra/
│   ├── mosquitto/mosquitto.conf        # cấu hình MQTT broker
│   └── grafana/provisioning/           # datasource + dashboard
└── services/
    ├── sensor/       # virtual sensor (sensor.py + Dockerfile)
    ├── actuator/     # virtual actuator (actuator.py + Dockerfile)
    ├── gateway/      # edge gateway: gateway.py, aqi.py, rules.py,
    │                 #   influx.py, thingsboard.py (thuần hàm, không OOP)
    ├── api/          # FastAPI REST API (main.py + Dockerfile)
    └── control-web/  # Web dashboard điều khiển
```

## Nhóm thực hiện

| Thành viên            | MSSV        | Mảng phụ trách                                |
| --------------------- | ----------- | --------------------------------------------- |
| Nguyễn Trường Chinh   | 20261101M   | Thiết bị ảo & thiết kế giao tiếp MQTT         |
| Nguyễn Hà Minh        | 20261102M   | Edge gateway & xử lý dữ liệu (AQI, rules)     |
| Đỗ Thành Đạt          | 20261103M   | Cloud, REST API, dashboard & triển khai       |
