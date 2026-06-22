FROM python:3.12-slim

WORKDIR /app

# Cài dependency trước để tận dụng cache layer của Docker.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sensor.py .

# Không buffer stdout để xem log realtime bằng `docker compose logs`.
ENV PYTHONUNBUFFERED=1

CMD ["python", "sensor.py"]
