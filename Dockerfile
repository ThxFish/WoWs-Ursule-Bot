FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    URSULE_DATA_DIR=/data \
    URSULE_HOST=0.0.0.0 \
    URSULE_PORT=8000

WORKDIR /app
COPY pyproject.toml ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY ursule_bot ./ursule_bot
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 ursule && mkdir -p /data/auth /data/backups && chown -R ursule:ursule /data /app
USER ursule

EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "-m", "ursule_bot"]
