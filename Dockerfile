FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRACKER_DATA_DIR=/data \
    TRACKER_HOST=0.0.0.0 \
    TRACKER_PORT=8000

WORKDIR /app
COPY pyproject.toml ./
COPY tracker ./tracker
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 tracker && mkdir -p /data/auth /data/backups && chown -R tracker:tracker /data /app
USER tracker

EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "-m", "tracker"]

