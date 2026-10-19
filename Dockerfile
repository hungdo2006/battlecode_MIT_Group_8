# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS application

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Bookworm provides matching Java 17 compiler/runtime and native C++17 tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates g++ openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 10001 arena \
    && useradd --uid 10001 --gid arena --create-home arena \
    && install -d -o arena -g arena /app/data /app/uploads

# Explicit copies keep host metadata, Windows artifacts and secrets out of image.
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/version_frontend.py ./scripts/version_frontend.py
RUN python scripts/version_frontend.py
COPY samples/ ./samples/
COPY run.py ./
COPY deploy/healthcheck.py ./deploy/healthcheck.py
COPY scripts/check_lan.py scripts/demo_match.py ./scripts/

USER arena:arena
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "deploy/healthcheck.py"]

# One worker: the data-volume writer lock rejects a second backend process.
# Exec form forwards SIGTERM; Compose init reaps orphaned children.
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--timeout-graceful-shutdown", "20"]

# Optional Linux regression image, never used by the Compose service.
FROM application AS tests
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
COPY scripts/backup_docker.py scripts/restore_docker.py scripts/volume_snapshot.py scripts/check_docker.py ./scripts/
COPY pytest.ini ./
COPY sandbox_controller/artifacts.py sandbox_controller/__init__.py ./sandbox_controller/
COPY docs/reference/ottv2/ ./docs/reference/ottv2/
RUN install -d -o arena -g arena /app/.pytest_cache
USER arena:arena
CMD ["python", "-m", "pytest", "-ra", "--tb=short"]

# Default docker build produces only the application (no Node/pytest/test data).
FROM application AS runtime
