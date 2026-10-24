FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt requirements-agents.txt requirements-gateway.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements-gateway.txt

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY src/ ./src/
COPY config/ ./config/
RUN useradd --create-home --uid 10001 pitchpulse \
    && chown -R pitchpulse:pitchpulse /app
USER pitchpulse
EXPOSE 8000
CMD ["uvicorn", "src.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
