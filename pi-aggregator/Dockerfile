FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Single worker: the forwarder background thread must not be started more
# than once, and ingest throughput from a handful of NodeMCUs is tiny.
CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:8080", "app:app"]
