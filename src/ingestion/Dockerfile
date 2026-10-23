FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system pitchpulse \
    && useradd --system --gid pitchpulse --home-dir /app pitchpulse

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY src/ingestion ./src/ingestion
COPY config/match-event.schema.json ./config/match-event.schema.json
USER pitchpulse

ENTRYPOINT ["python", "-m", "src.ingestion.producer"]
