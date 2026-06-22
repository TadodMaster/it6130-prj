FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aqi.py rules.py influx.py thingsboard.py gateway.py ./

ENV PYTHONUNBUFFERED=1

CMD ["python", "gateway.py"]
