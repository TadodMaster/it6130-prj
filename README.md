# Virtual Smart Air Quality Gateway (Đề tài 4 - IT6130)

Hệ thống Virtual IoT Gateway giám sát chất lượng không khí đô thị: thu thập bụi mịn
và khí ô nhiễm tại nhiều trạm, tính chỉ số AQI, tự động điều khiển quạt thông gió /
máy lọc khí / phun sương / bảng cảnh báo qua MQTT, lưu InfluxDB, dashboard Grafana,
và đồng bộ hai chiều với ThingsBoard Cloud (telemetry + RPC).

## Kiến trúc

```
 Virtual Sensors  ─┐                              ┌─ InfluxDB (time-series)
 (station 01/02/03)│        ┌──────────────┐      │
                   ├─ MQTT ─┤ Edge Gateway ├──────┤
 Virtual Actuators │ broker │ AQI + rules  │      └─ Grafana (dashboard)
 (fan/purifier/... )┘(mosq.) │ TB gateway   │
                            └──────┬───────┘
        FastAPI REST API ─────────┘   │
                                      └────► ThingsBoard Cloud (telemetry + RPC)
```

## Các service

| Service              | Mô tả                                   |
|----------------------|-----------------------------------------|
| `mosquitto`          | MQTT broker                             |
| `sensor-station-0X`  | Virtual sensor mỗi trạm                  |
| `actuator-station-0X`| Virtual actuator mỗi trạm                |
| `air-gateway`        | Edge gateway: AQI, rule engine, TB sync |
| `influxdb`           | Time-series database                    |
| `grafana`            | Dashboard edge                          |
| `air-api`            | REST API (FastAPI)                      |

## Chạy hệ thống

```bash
cp .env.example .env   # chỉnh sửa nếu cần
docker compose up -d --build
docker compose ps
docker compose logs -f air-gateway
```

## Cổng truy cập

| Service     | URL                       |
|-------------|---------------------------|
| Grafana     | http://localhost:3000     |
| InfluxDB    | http://localhost:8086     |
| FastAPI     | http://localhost:8000/docs|
| MQTT broker | localhost:1883            |

## Cấu trúc thư mục

```
it6130-prj/
├── docker-compose.yml
├── .env / .env.example
├── pyproject.toml
├── infra/
│   ├── mosquitto/mosquitto.conf        # cấu hình MQTT broker
│   └── grafana/provisioning/           # datasource + dashboard
└── services/
    ├── sensor/      # virtual sensor (sensor.py + Dockerfile)
    ├── actuator/    # virtual actuator (actuator.py + Dockerfile)
    ├── gateway/     # edge gateway: gateway.py, aqi.py, rules.py,
    │                #   influx.py, thingsboard.py (thuần hàm, không OOP)
    └── api/         # FastAPI REST API (main.py + Dockerfile)
```
