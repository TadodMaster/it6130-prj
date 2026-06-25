import os
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

API_BASE = os.getenv("API_BASE", "http://air-api:8000").rstrip("/")
REFRESH_MS = int(os.getenv("REFRESH_MS", "3000"))
STATIONS = os.getenv("STATIONS", "station-01,station-02,station-03").split(",")
TIMEOUT = 4  # giây

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Air Quality Control Web", version="1.0")


# --------------------------------------------------------------------------- #
# Trang dashboard
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return (html
            .replace("__REFRESH_MS__", str(REFRESH_MS))
            .replace("__STATIONS__", ",".join(s.strip() for s in STATIONS)))


# --------------------------------------------------------------------------- #
# Proxy sang gateway API (air-api)
# --------------------------------------------------------------------------- #
def _get(path: str):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        raise HTTPException(502, f"gateway API lỗi: {exc}") from exc


@app.get("/api/health")
def health():
    return _get("/health")


@app.get("/api/stations/{station_id}/state")
def station_state(station_id: str):
    # Trạm chưa có dữ liệu -> air-api trả 404; web coi như state rỗng.
    try:
        r = requests.get(f"{API_BASE}/stations/{station_id}/state", timeout=TIMEOUT)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        raise HTTPException(502, f"gateway API lỗi: {exc}") from exc


@app.get("/api/stations/{station_id}/events")
def station_events(station_id: str, limit: int = 8):
    return _get(f"/stations/{station_id}/events?limit={limit}")


@app.post("/api/stations/{station_id}/command")
async def send_command(station_id: str, request: Request):
    body = await request.json()
    try:
        r = requests.post(f"{API_BASE}/stations/{station_id}/command",
                          json=body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        raise HTTPException(502, f"gateway API lỗi: {exc}") from exc
